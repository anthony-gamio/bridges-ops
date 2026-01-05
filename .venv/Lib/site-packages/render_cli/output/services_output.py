"""Helpers to format the Render services information."""
from rich.table import Table

SERVICES_TABLE_TITLE = "SERVICES"

SERVICE_NAME_COL_HEADER = "Name"
SERVICES_ID_COL_HEADER = "Id"
SERVICES_URL_COL_HEADER = "Url"

services_columns = [
    SERVICE_NAME_COL_HEADER,
    SERVICES_ID_COL_HEADER,
    SERVICES_URL_COL_HEADER,
]

ENV_VARS_TABLE_TITLE = "ENVIRONMENT VARIABLES"
ENV_VARS_NAME_COL_HEADER = "Name"
ENV_VARS_VALUE_COL_HEADER = "Value"

env_vars_columns = [ENV_VARS_NAME_COL_HEADER, ENV_VARS_VALUE_COL_HEADER]


def output_services_as_table(data):
    """Formats the service data as a table using the Rich text library."""
    tb = Table(title=SERVICES_TABLE_TITLE)
    for header in services_columns:
        tb.add_column(header)
    for item in data:
        service = item["service"]
        service_details = service["serviceDetails"]
        tb.add_row(service["name"], service["id"], service_details["url"])
    return tb


def output_env_vars_as_table(data):
    """Formats service env vars as a table using the Rich text library."""
    tb = Table(title=ENV_VARS_TABLE_TITLE)
    for header in env_vars_columns:
        tb.add_column(header)
    for item in data:
        env_var = item["envVar"]
        tb.add_row(env_var["key"], env_var["value"])
    return tb
