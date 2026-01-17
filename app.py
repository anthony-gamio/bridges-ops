# app.py (versión pulida, estable y lista para multi-almacén)

from flask import Flask, render_template, request, redirect, url_for
import os

# Carga .env solo en local (en Render no hace falta)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ModuleNotFoundError:
    pass

import pandas as pd
from sqlalchemy import (
    create_engine, Column, Integer, String, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base


app = Flask(__name__)

# =========================
# DB CONFIG
# =========================
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("La variable de entorno DATABASE_URL no está configurada.")

# Render a veces da postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# sslmode para Render Postgres
if "sslmode=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=require"

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
Session = sessionmaker(bind=engine)
Base = declarative_base()

# =========================
# MODELS
# =========================
class Area(Base):
    __tablename__ = "areas"
    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False, unique=True)

    materiales = relationship("Material", backref="area", cascade="all, delete-orphan")


class Material(Base):
    __tablename__ = "materiales"
    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False)
    area_id = Column(Integer, ForeignKey("areas.id"), nullable=False)

    asignaciones = relationship("AsignacionItem", backref="material", cascade="all, delete-orphan")


class Inventario(Base):
    __tablename__ = "inventario"
    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False, unique=True)

    # NOTA: cantidad ya NO es la fuente de verdad; el stock real es Stock
    # La dejamos para compatibilidad con tu CSV/legacy.
    cantidad = Column(Integer, nullable=False, default=0)

    categoria = Column(String, nullable=False)
    consumo_estimado = Column(Integer, default=0)

    stocks = relationship("Stock", backref="item", cascade="all, delete-orphan")


class Almacen(Base):
    __tablename__ = "almacenes"
    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False, unique=True)

    stocks = relationship("Stock", backref="almacen", cascade="all, delete-orphan")


class Stock(Base):
    __tablename__ = "stock"
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("inventario.id"), nullable=False)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=False)
    cantidad = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("item_id", "almacen_id", name="uq_stock_item_almacen"),
    )


class AsignacionItem(Base):
    __tablename__ = "asignacion_items"
    id = Column(Integer, primary_key=True)
    material_id = Column(Integer, ForeignKey("materiales.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("inventario.id"), nullable=False)
    cantidad_asignada = Column(Integer, nullable=False)

    item = relationship("Inventario", backref="asignaciones")


# =========================
# INIT / SEEDS
# =========================
Base.metadata.create_all(engine)


def seed_almacenes():
    s = Session()
    try:
        if s.query(Almacen).count() == 0:
            s.add_all([
                Almacen(nombre="Almacén PNSR"),
                Almacen(nombre="St Joe's Schack"),
                Almacen(nombre="Almacén Pamplona"),
            ])
            s.commit()
    finally:
        s.close()


def _get_or_create_almacen_principal_id(s) -> int:
    a = s.query(Almacen).filter_by(nombre="Almacén PNSR").first()
    if not a:
        a = Almacen(nombre="Almacén PNSR")
        s.add(a)
        s.flush()
    return a.id


def cargar_csv_inicial():
    """
    Si la tabla inventario está vacía, carga inventario.csv.
    IMPORTANTE: el stock real se guarda en Stock en el Almacén Principal.
    """
    s = Session()
    try:
        if s.query(Inventario).count() > 0:
            print("La tabla ya contiene datos. No se cargará el CSV.")
            return

        csv_path = "inventario.csv"
        if not os.path.exists(csv_path):
            print(f"El archivo {csv_path} no existe.")
            return

        almacen_principal_id = _get_or_create_almacen_principal_id(s)

        df = pd.read_csv(csv_path)
        for _, row in df.iterrows():
            nombre = str(row["nombre"]).strip()
            cantidad = int(row["cantidad"])
            categoria = str(row["categoria"]).strip()
            consumo_estimado = int(row.get("consumo_estimado", 0) or 0)

            item = Inventario(
                nombre=nombre,
                cantidad=0,  # legacy, no se usa como stock real
                categoria=categoria,
                consumo_estimado=consumo_estimado
            )
            s.add(item)
            s.flush()

            s.add(Stock(item_id=item.id, almacen_id=almacen_principal_id, cantidad=cantidad))

        s.commit()
        print("Datos cargados exitosamente desde el CSV (stock en Almacén Principal).")
    finally:
        s.close()


seed_almacenes()
cargar_csv_inicial()


# =========================
# HELPERS
# =========================
def _semaforo(stock: int, estimado: int) -> str:
    if stock >= estimado:
        return "VERDE"
    if stock > 0 and stock < estimado:
        return "AMARILLO"
    return "ROJO"


def _stock_consolidado_por_item(s) -> dict:
    """
    Devuelve {item_id: total} sumando todos los almacenes.
    """
    totals = {}
    rows = s.query(Stock.item_id, Stock.cantidad).all()
    for item_id, cant in rows:
        totals[item_id] = totals.get(item_id, 0) + (cant or 0)
    return totals


# =========================
# ROUTES
# =========================
@app.route("/")
def index():
    s = Session()
    try:
        almacenes = s.query(Almacen).order_by(Almacen.nombre).all()
        if not almacenes:
            return "No hay almacenes creados", 500

        # "all" o id
        view_almacen = request.args.get("almacen_id", default="all")

        inventario = s.query(Inventario).order_by(Inventario.nombre).all()

        # Mapa consolidado
        total_map = _stock_consolidado_por_item(s)

        # Si filtras almacén específico, mapa por almacén
        stock_map = None
        almacen_id_int = None
        if view_almacen != "all":
            almacen_id_int = int(view_almacen)
            rows = s.query(Stock.item_id, Stock.cantidad).filter_by(almacen_id=almacen_id_int).all()
            stock_map = {item_id: (cant or 0) for item_id, cant in rows}

        return render_template(
            "index.html",
            inventario=inventario,
            modo_admin=False,
            almacenes=almacenes,
            view_almacen=view_almacen,
            almacen_id=almacen_id_int,
            total_map=total_map,
            stock_map=stock_map,
        )
    finally:
        s.close()


@app.route("/inventario/<int:item_id>/distribucion")
def distribucion_item(item_id):
    s = Session()
    try:
        item = s.get(Inventario, item_id)
        if not item:
            return "Ítem no encontrado", 404

        rows = (
            s.query(Stock, Almacen)
            .join(Almacen, Stock.almacen_id == Almacen.id)
            .filter(Stock.item_id == item_id, Stock.cantidad > 0)
            .order_by(Almacen.nombre)
            .all()
        )

        return render_template("distribucion_partial.html", item=item, rows=rows)
    finally:
        s.close()


@app.route("/agregar", methods=["POST"])
def agregar():
    """
    Movimiento simple (entrada). Para salidas/egresos lo extendemos luego.
    """
    s = Session()
    try:
        nombre = request.form["nombre"].strip()
        cantidad = int(request.form["cantidad"])
        categoria = (request.form.get("categoria") or "").strip()
        if not categoria:
            categoria = "Sin categoría"

        almacen_mov_id = int(request.form["almacen_movimiento_id"])

        # Ítem único por nombre (no puede ser Activo y Consumible a la vez)
        item = s.query(Inventario).filter_by(nombre=nombre).first()
        if item:
            if item.categoria != categoria:
                return "Ese ítem ya existe con otra categoría. No puede ser Activo y Consumible a la vez.", 400
        else:
            item = Inventario(nombre=nombre, cantidad=0, categoria=categoria)
            s.add(item)
            s.flush()

        st = s.query(Stock).filter_by(item_id=item.id, almacen_id=almacen_mov_id).first()
        if st:
            st.cantidad += cantidad
        else:
            s.add(Stock(item_id=item.id, almacen_id=almacen_mov_id, cantidad=cantidad))

        s.commit()

        # vuelve a la vista actual (si no hay param, queda all)
        view_almacen = request.args.get("almacen_id", default="all")
        return redirect(url_for("index", almacen_id=view_almacen))
    finally:
        s.close()


@app.route("/inventario/eliminar/<int:item_id>", methods=["POST"])
def eliminar_item_inventario(item_id):
    s = Session()
    try:
        item = s.get(Inventario, item_id)
        if not item:
            return "Ítem no encontrado", 404

        # elimina asignaciones y stocks relacionados
        s.query(AsignacionItem).filter_by(item_id=item_id).delete()
        s.query(Stock).filter_by(item_id=item_id).delete()

        s.delete(item)
        s.commit()
        return redirect(url_for("index"))
    finally:
        s.close()


@app.route("/requerimientos")
def requerimientos():
    s = Session()
    try:
        total_map = _stock_consolidado_por_item(s)
        reqs = []

        items = s.query(Inventario).all()
        for it in items:
            estimado = it.consumo_estimado or 0
            stock = total_map.get(it.id, 0)
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

        prioridad = {"ROJO": 0, "AMARILLO": 1, "VERDE": 2}
        reqs.sort(key=lambda r: (prioridad[r["semaforo"]], -r["faltante"]))

        return render_template("requerimientos.html", requerimientos=reqs)
    finally:
        s.close()


# =========================
# AREAS / MATERIALES (campañas)
# =========================
@app.route("/areas")
def areas():
    s = Session()
    try:
        todas_areas = s.query(Area).all()
        return render_template("gestionar_areas.html", areas=todas_areas)
    finally:
        s.close()


@app.route("/areas/agregar", methods=["POST"])
def agregar_area():
    s = Session()
    try:
        nombre_area = request.form.get("nombre_area")
        if nombre_area:
            s.add(Area(nombre=nombre_area))
            s.commit()
        return redirect(url_for("areas"))
    finally:
        s.close()


@app.route("/areas/eliminar/<int:area_id>", methods=["POST"])
def eliminar_area(area_id):
    s = Session()
    try:
        area = s.get(Area, area_id)
        if not area:
            return "Área no encontrada", 404
        s.delete(area)
        s.commit()
        return redirect(url_for("areas"))
    finally:
        s.close()


@app.route("/areas/<int:area_id>/materiales")
def ver_materiales(area_id):
    s = Session()
    try:
        area = s.get(Area, area_id)
        if not area:
            return "Área no encontrada", 404
        materiales = s.query(Material).filter_by(area_id=area.id).all()
        return render_template("materiales_partial.html", materiales=materiales, area=area)
    finally:
        s.close()


@app.route("/materiales/agregar/<int:area_id>", methods=["POST"])
def agregar_material(area_id):
    s = Session()
    try:
        nombre_material = request.form.get("nombre_material")
        if not nombre_material:
            return "Error: No se recibió el nombre del material", 400

        s.add(Material(nombre=nombre_material, area_id=area_id))
        s.commit()
        return "Material agregado", 200
    finally:
        s.close()


@app.route("/materiales/eliminar/<int:material_id>", methods=["POST"])
def eliminar_material(material_id):
    s = Session()
    try:
        material = s.get(Material, material_id)
        if not material:
            return "Material no encontrado", 404

        area_id = material.area_id
        s.delete(material)
        s.commit()
        return redirect(url_for("ver_materiales", area_id=area_id))
    finally:
        s.close()


@app.route("/asignar_items/<int:material_id>")
def ver_asignacion_items(material_id):
    s = Session()
    try:
        material = s.get(Material, material_id)
        if not material:
            return "Material no encontrado", 404

        inventario = s.query(Inventario).all()
        asignaciones = s.query(AsignacionItem).filter_by(material_id=material_id).all()
        return render_template(
            "asignar_items_partial.html",
            material=material,
            inventario=inventario,
            asignaciones=asignaciones
        )
    finally:
        s.close()


@app.route("/asignar_items/<int:material_id>", methods=["POST"])
def asignar_items(material_id):
    s = Session()
    try:
        item_id = int(request.form.get("item_id"))
        cantidad_asignada = int(request.form.get("cantidad_asignada"))

        asignacion = (
            s.query(AsignacionItem)
            .filter_by(material_id=material_id, item_id=item_id)
            .first()
        )
        if asignacion:
            asignacion.cantidad_asignada += cantidad_asignada
        else:
            s.add(AsignacionItem(
                material_id=material_id,
                item_id=item_id,
                cantidad_asignada=cantidad_asignada
            ))

        item = s.get(Inventario, item_id)
        if item:
            item.consumo_estimado = (item.consumo_estimado or 0) + cantidad_asignada

        s.commit()
        return redirect(url_for("ver_asignacion_items", material_id=material_id))
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


@app.route("/asignar_items/eliminar/<int:asignacion_id>", methods=["POST"])
def eliminar_asignacion(asignacion_id):
    s = Session()
    try:
        asignacion = s.get(AsignacionItem, asignacion_id)
        if not asignacion:
            return "Asignación no encontrada", 404

        item = s.get(Inventario, asignacion.item_id)
        if item:
            item.consumo_estimado = max(0, (item.consumo_estimado or 0) - asignacion.cantidad_asignada)

        material_id = asignacion.material_id
        s.delete(asignacion)
        s.commit()
        return redirect(url_for("ver_asignacion_items", material_id=material_id))
    finally:
        s.close()


# =========================
# ACTIVIDADES (CSV)
# =========================
@app.route("/actividades")
def actividades():
    actividades_path = "actividades.csv"

    if os.path.exists(actividades_path):
        try:
            df = pd.read_csv(actividades_path, encoding="utf-8")
            df["Estado"] = df["Estado"].astype(bool)

            dias_ordenados = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            df["Día"] = df["Día"].str.capitalize()
            df["Día"] = pd.Categorical(df["Día"], categories=dias_ordenados, ordered=True)
            df = df.sort_values("Día")
            actividades_data = df.to_dict(orient="records")
        except Exception as e:
            return f"<h2>Error al leer el CSV:</h2><p>{e}</p>", 500
    else:
        actividades_data = []

    return render_template("actividades.html", actividades=actividades_data)


@app.route("/actualizar_actividades", methods=["POST"])
def actualizar_actividades():
    actividades_path = "actividades.csv"
    df = pd.read_csv(actividades_path, encoding="utf-8")

    for i in range(len(df)):
        checkbox_name = f"completado_{i}"
        df.at[i, "Estado"] = checkbox_name in request.form

    df.to_csv(actividades_path, index=False)
    return redirect(url_for("actividades"))


if __name__ == "__main__":
    app.run(debug=True)
