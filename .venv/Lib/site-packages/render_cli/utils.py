"""Utility for dealing with env vars."""


def convert_env_var_file(env_var_file_name: str) -> dict:
    """Converts env file into key value for sending to Render."""
    """
        env var file format is
        var1=value1
        var2=value2
        ....
    """
    env_vars_from_file = {}
    with open(env_var_file_name) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            else:
                var, value = line.split("=")
                env_vars_from_file[var.strip()] = value.strip()
    return env_vars_from_file


def convert_from_render_env_format(env_vars) -> dict:
    """Converts json response from env vars to dict of env vars."""
    """ env vars from the Render call are returned in the following format
        [
            {
                "envVar": {
                    "key": "var3",
                    "value": "new3"
                },
                "cursor": "XC18_l2WbtJ2cTRncWc0ZGxmZDNuZ2Mw"
            },
            {
                "envVar": {
                    "key": "var2",
                    "value": "new2"
                },
                "cursor": "XC18_l2WbtJ2cTRncWc0ZGxmZDNuZ2Jn"
          }
        ]
    """
    evs = {}
    for env_var in env_vars:
        ev = env_var["envVar"]
        evs[ev["key"]] = ev["value"]
    return evs


def convert_to_render_env_format(env_vars: dict) -> list[dict]:
    """Converts a dict to a list[dict] with format for render api."""
    """ env var payload for Render looks like
        [
            {"key": "env_var_name_1", "value": "env_var_value_1"},
            {"key": "env_var_name_2", "value": "env_var_value_2"},
            ....
        ]
    """
    results = []
    for key, value in env_vars.items():
        results.append({"key": key, "value": value})
    return results
