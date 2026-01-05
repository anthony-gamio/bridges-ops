"""Render Command-line interface."""
import json
from typing import Any

import click
from rich.console import Console

from render_cli.output.services_output import (
    output_env_vars_as_table,
    output_services_as_table,
)
import render_cli.render_services as rs
from render_cli.utils import (
    convert_env_var_file,
    convert_from_render_env_format,
    convert_to_render_env_format,
)

# from . import __version__

__version__ = "3.0"


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """A cli to manage your Render services."""
    pass


@cli.command("list")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Display full json output from render api call.",
)
def list_services(verbose) -> Any:
    """Returns a list of all services associated with your Render account.

    Args:
        verbose: option to return a formatted json dump of all services
            instead of the default table view which just displays the
            service name, service id and service url.
    """
    data = rs.fetch_services()
    if verbose:
        click.echo(json.dumps(data, indent=4))
    else:
        console = Console()
        click.echo("\n")
        console.print(output_services_as_table(data))


@cli.command("find-service")
@click.option("-sn", "--service-name", type=str, help="Find service by name")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Display full json output from render api call.",
)
def find_service(service_name, verbose) -> Any:
    """Finds a Render service by name.

    Returns information about service if found.

    Args:
        service_name: name of service to search for.
        verbose: option to return a formatted json dump of all services
            instead of the default table view which just displays the
            service name, service id and service url.
    """
    data = rs.find_service_by_name(service_name)
    if verbose:
        click.echo(json.dumps(data, indent=4))
    else:
        console = Console()
        click.echo("\n")
        console.print(output_services_as_table([data]))


@cli.command("set-env")
@click.option("-f", "--file", type=str, help="File to load env vars from")
@click.option("-sn", "--service-name", type=str, help="Render service name")
@click.option(
    "-u",
    "--update",
    is_flag=True,
    help="Will update env vars with those in file rather completely overwrite.",
)
def set_env(file: str, service_name: str, update: bool) -> Any:
    """Will set environment variables for the specified service.

    This is completely replace all environment variables for a
    service with those provided here.

    Args:
        file: path to file containing the environment variables to set.
        service_name: name of service to set env vars for.
        update: update flag to indicate update env vars instead of overwrite.

    """
    service_id = rs.find_service_by_name(service_name)["service"]["id"]
    env_vars = convert_env_var_file(file)
    current_env_vars = (
        convert_from_render_env_format(rs.retrieve_env_from_render(service_id))
        if update
        else {}
    )
    rs.set_env_variables_for_service(
        service_id, convert_to_render_env_format({**current_env_vars, **env_vars})
    )


@cli.command("list-env")
@click.option("-sid", "--service-id", type=str, help="Render service id")
@click.option("-sn", "--service-name", type=str, help="Render service name")
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Display full json output from render api call.",
)
def list_env(service_id, service_name, verbose) -> Any:
    """Fetches list of environment variables of a service.

    Returns and lists the environment variables associated with
        the passed in service id or service name.  Verbose mode
        will display json.

    Args:
        service_id: id of service whose environment variables to find.
        service_name: name of service whose environment variables to find.
        verbose: option to return a formatted json dump of all environment
            variable information.

    """
    if not service_id:
        if service_name:
            service_id = rs.find_service_by_name(service_name)["service"]["id"]
        else:
            click.echo("Need to provide service id or service name options")
            exit()
    data = rs.retrieve_env_from_render(service_id)
    if verbose:
        click.echo(json.dumps(data, indent=4))
    else:
        console = Console()
        click.echo("\n")
        console.print(output_env_vars_as_table(data))


def recursive_help(cmd, parent=None) -> None:
    """Helper function to dump the help of a command.

    Args:
        cmd: command to get help for
        parent: parent command

    """
    ctx = click.core.Context(cmd, info_name=cmd.name, parent=parent)
    print(cmd.get_help(ctx))
    print()
    commands = getattr(cmd, "commands", {})
    for sub in commands.values():
        recursive_help(sub, ctx)


@cli.command("dump-help")
def dump_help() -> None:
    """Command to dump all help screen."""
    recursive_help(cli)
