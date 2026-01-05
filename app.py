from flask import Flask, render_template, request, redirect, url_for, jsonify
import os
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from urllib.parse import quote_plus
import psycopg2

app = Flask(__name__)

# Configuración de la base de datos
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("La variable de entorno DATABASE_URL no está configurada.")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DATABASE_URL += "?sslmode=require"

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
Session = sessionmaker(bind=engine)
session = Session()

@app.teardown_request
def _teardown_request(exc):
    try:
        if exc:
            session.rollback()   # deshace si hubo error
    except Exception:
        pass
    try:
        session.close()          # libera siempre la conexión
    except Exception:
        pass


# Definición del modelo
Base = declarative_base()

class Area(Base):
    __tablename__ = 'areas'
    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False, unique=True)

    materiales = relationship(
        'Material',
        backref='area',
        cascade="all, delete-orphan"
    )

class Material(Base):
    __tablename__ = 'materiales'
    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False)
    area_id = Column(Integer, ForeignKey('areas.id'), nullable=False)
    asignaciones = relationship('AsignacionItem', backref='material', cascade="all, delete-orphan")

class Inventario(Base):
    __tablename__ = 'inventario'
    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False)
    cantidad = Column(Integer, nullable=False)
    categoria = Column(String, nullable=False)
    consumo_estimado = Column(Integer, default=0)

class AsignacionItem(Base):
    __tablename__ = 'asignacion_items'
    id = Column(Integer, primary_key=True)
    material_id = Column(Integer, ForeignKey('materiales.id'), nullable=False)
    item_id = Column(Integer, ForeignKey('inventario.id'), nullable=False)
    cantidad_asignada = Column(Integer, nullable=False)
    item = relationship('Inventario', backref='asignaciones')

# Crear tablas si no existen
Base.metadata.create_all(engine)

# Función para vaciar la tabla inicial
def reiniciar_tabla():
    if os.getenv('FLASK_ENV') == 'development':
        session.query(AsignacionItem).delete()
        session.query(Inventario).delete()
        session.commit()
        print("Las tablas 'inventario' y 'asignacion_items' han sido vaciadas en el entorno local.")
    else:
        print("No se vacía la tabla en producción.")

# Cargar CSV solo si la tabla está vacía
def cargar_csv_inicial():
    if session.query(Inventario).count() == 0:
        csv_path = 'inventario.csv'
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            for _, row in df.iterrows():
                item = Inventario(
                    nombre=row['nombre'],
                    cantidad=row['cantidad'],
                    categoria=row['categoria'],
                    consumo_estimado=row.get('consumo_estimado', 0)
                )
                session.add(item)
            session.commit()
            print("Datos cargados exitosamente desde el CSV.")
        else:
            print(f"El archivo {csv_path} no existe.")
    else:
        print("La tabla ya contiene datos. No se cargará el CSV.")

# Llamar a la función al iniciar la aplicación
cargar_csv_inicial()

def _semaforo(stock: int, estimado: int) -> str:
    if stock >= estimado:
        return "VERDE"
    if stock > 0 and stock < estimado:
        return "AMARILLO"
    return "ROJO"

@app.route('/requerimientos')
def requerimientos():
    s = Session()
    try:
        reqs = []
        items = s.query(Inventario).all()
        for it in items:
            estimado = it.consumo_estimado or 0
            stock = it.cantidad or 0
            faltante = max(0, estimado - stock)
            color = _semaforo(stock, estimado)
            if estimado > 0 or faltante > 0:
                reqs.append({
                    "id": it.id,
                    "nombre": it.nombre,
                    "categoria": it.categoria,
                    "stock": stock,
                    "estimado": estimado,
                    "faltante": faltante,
                    "semaforo": color
                })
        # Orden útil: ROJO > AMARILLO > VERDE, y dentro por faltante desc
        prioridad = {"ROJO": 0, "AMARILLO": 1, "VERDE": 2}
        reqs.sort(key=lambda r: (prioridad[r["semaforo"]], -r["faltante"]))
        return render_template('requerimientos.html', requerimientos=reqs)
    finally:
        s.close()


@app.route('/')
def index():
    session = Session()  # Crear una nueva sesión
    try:
        inventario = session.query(Inventario).all()
        return render_template('index.html', inventario=inventario, modo_admin=False)
    finally:
        session.close()  # Cerrar la sesión después de usarla

@app.route('/agregar', methods=['POST'])
def agregar():
    nombre = request.form['nombre']
    cantidad = int(request.form['cantidad'])
    categoria = request.form['categoria']

    item_existente = session.query(Inventario).filter_by(nombre=nombre, categoria=categoria).first()

    if item_existente:
        item_existente.cantidad += cantidad
        session.commit()
    else:
        nuevo_item = Inventario(nombre=nombre, cantidad=cantidad, categoria=categoria)
        session.add(nuevo_item)
        session.commit()

    return redirect(url_for('index'))

@app.route('/inventario/eliminar/<int:item_id>', methods=['POST'])
def eliminar_item_inventario(item_id):
    s = Session()
    try:
        item = s.get(Inventario, item_id)
        if not item:
            return "Ítem no encontrado", 404

        # Eliminar asignaciones relacionadas a este ítem (evita FK rotas)
        s.query(AsignacionItem).filter_by(item_id=item_id).delete()

        # Eliminar el ítem de inventario
        s.delete(item)
        s.commit()
        return redirect(url_for('index'))
    finally:
        s.close()

@app.route('/areas')
def areas():
    session = Session()
    try:
        todas_areas = session.query(Area).all()
        return render_template('gestionar_areas.html', areas=todas_areas)
    finally:
        session.close()

@app.route('/areas/agregar', methods=['POST'])
def agregar_area():
    session = Session()
    try:
        nombre_area = request.form.get('nombre_area')
        if nombre_area:
            nueva_area = Area(nombre=nombre_area)
            session.add(nueva_area)
            session.commit()
        return redirect(url_for('areas'))
    finally:
        session.close()

@app.route('/areas/eliminar/<int:area_id>', methods=['POST'])
def eliminar_area(area_id):
    session = Session()
    try:
        area = session.query(Area).get(area_id)
        if not area:
            return "Área no encontrada", 404
        session.delete(area)
        session.commit()
        return redirect(url_for('areas'))
    finally:
        session.close()

@app.route('/areas/<int:area_id>/materiales')
def ver_materiales(area_id):
    session = Session()
    try:
        area = session.query(Area).get(area_id)
        if not area:
            return "Área no encontrada", 404
        materiales = session.query(Material).filter_by(area_id=area.id).all()
        return render_template('materiales_partial.html', materiales=materiales, area=area)
    finally:
        session.close()


@app.route('/materiales/agregar/<int:area_id>', methods=['POST'])
def agregar_material(area_id):
    session = Session()
    try:
        nombre_material = request.form.get('nombre_material')
        print(f"Recibido: {nombre_material}")

        if not nombre_material:
            return "Error: No se recibió el nombre del material", 400

        nuevo_material = Material(nombre=nombre_material, area_id=area_id)
        session.add(nuevo_material)
        session.commit()
        print("Material agregado correctamente")
        return "Material agregado", 200
    finally:
        session.close()


@app.route('/materiales/eliminar/<int:material_id>', methods=['POST'])
def eliminar_material(material_id):
    session = Session()
    try:
        material = session.query(Material).get(material_id)
        if not material:
            return "Material no encontrado", 404
        area_id = material.area_id
        session.delete(material)
        session.commit()
        print(f"Material {material_id} eliminado correctamente")
        return redirect(url_for('ver_materiales', area_id=area_id))
    finally:
        session.close()


@app.route('/asignar_items/<int:material_id>')
def ver_asignacion_items(material_id):
    material = session.query(Material).get(material_id)
    if not material:
        return "Material no encontrado", 404
    inventario = session.query(Inventario).all()
    asignaciones = session.query(AsignacionItem).filter_by(material_id=material_id).all()
    return render_template('asignar_items_partial.html', material=material, inventario=inventario, asignaciones=asignaciones)


@app.route('/asignar_items/<int:material_id>', methods=['POST'])
def asignar_items(material_id):
    try:
        item_id = int(request.form.get('item_id'))
        cantidad_asignada = int(request.form.get('cantidad_asignada'))

        asignacion_existente = session.query(AsignacionItem).filter_by(
            material_id=material_id, item_id=item_id).first()

        if asignacion_existente:
            asignacion_existente.cantidad_asignada += cantidad_asignada
        else:
            session.add(AsignacionItem(material_id=material_id,
                                       item_id=item_id,
                                       cantidad_asignada=cantidad_asignada))

        item_inventario = session.query(Inventario).get(item_id)
        if item_inventario:
            item_inventario.consumo_estimado += cantidad_asignada  # si esa columna existe

        session.commit()
        return redirect(url_for('ver_asignacion_items', material_id=material_id))
    except Exception:
        session.rollback()   # <— clave
        raise

@app.route('/asignar_items/eliminar/<int:asignacion_id>', methods=['POST'])
def eliminar_asignacion(asignacion_id):
    asignacion = session.query(AsignacionItem).get(asignacion_id)
    if not asignacion:
        return "Asignación no encontrada", 404

    item_inventario = session.query(Inventario).get(asignacion.item_id)
    if item_inventario:
        item_inventario.consumo_estimado -= asignacion.cantidad_asignada

    session.delete(asignacion)
    session.commit()
    return redirect(url_for('ver_asignacion_items', material_id=asignacion.material_id))

@app.route('/actividades')
def actividades():
    actividades_path = 'actividades.csv'
    
    if os.path.exists(actividades_path):
        try:
            df = pd.read_csv(actividades_path, encoding='utf-8')
            df['Estado'] = df['Estado'].astype(bool)
            dias_ordenados = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
            df['Día'] = df['Día'].str.capitalize()
            df['Día'] = pd.Categorical(df['Día'], categories=dias_ordenados, ordered=True)
            df = df.sort_values('Día')
            actividades = df.to_dict(orient='records')
        except Exception as e:
            return f"<h2>Error al leer el CSV:</h2><p>{e}</p>", 500
    else:
        actividades = []

    return render_template('actividades.html', actividades=actividades)

@app.route('/actualizar_actividades', methods=['POST'])
def actualizar_actividades():
    actividades_path = 'actividades.csv'
    df = pd.read_csv(actividades_path, encoding='utf-8')

    # Actualizar el estado de 'Estado' según los checkboxes enviados
    for i in range(len(df)):
        checkbox_name = f'completado_{i}'
        df.at[i, 'Estado'] = checkbox_name in request.form  # True si está marcado, False si no

    # Guardar los cambios en el CSV
    df.to_csv(actividades_path, index=False)

    return redirect(url_for('actividades'))

if __name__ == '__main__':
    app.run(debug=True)
