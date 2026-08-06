import json
import logging
import time
from typing import Tuple, Dict, Any

# Suppress SyntaxWarning from slpp on Python 3.12+
import warnings

warnings.filterwarnings("ignore", category=SyntaxWarning, module="slpp")

from slpp import slpp as lua

from fle.env.entities import Direction
from fle.env.lua_manager import LuaScriptManager
from fle.env.namespace import FactorioNamespace
from fle.env.utils.rcon import _lua2python, _remove_numerical_keys

logger = logging.getLogger(__name__)

COMMAND = "/silent-command"

# Marker emitted by encode_result in fle/env/mods/utils.lua. Everything after
# it is a JSON object {"a": <pcall ok>, "b": <result>}.
JSON_PREFIX = "###FLE:J###"

# Maximum retries for RCON [processing] errors
MAX_PROCESSING_RETRIES = 3
PROCESSING_RETRY_DELAY = 0.1  # seconds


class RconProcessingError(Exception):
    """Raised when RCON returns [processing] indicating game engine is busy"""

    pass


def _strip_quotes(s):
    """Strip one surrounding quote layer from a string value.

    serialize.lua pre-wraps many string values in literal quote characters (a
    workaround for dump() never quoting strings, which the old Lua-literal
    parser then consumed as string delimiters). Clients historically received
    the unwrapped value.
    """
    if isinstance(s, str) and len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _luaify(obj):
    """Normalize a JSON-decoded Lua table to the shapes slpp produced.

    The old slpp parser represented every Lua table as a dict, with numeric
    keys as ints (a Lua list arrived as {1: ..., 2: ...}). helpers.table_to_json
    instead emits dense numeric tables as JSON arrays and sparse ones as
    objects with digit-string keys. Convert both back to 1-indexed int-keyed
    dicts; the historical top-level list conversion is then applied by
    _remove_numerical_keys, exactly as on the old parse path.
    """
    if isinstance(obj, list):
        return {i + 1: _luaify(v) for i, v in enumerate(obj)}
    if isinstance(obj, dict):
        return {
            (int(k) if isinstance(k, str) and k.lstrip("-").isdigit() else k): (
                _luaify(v)
            )
            for k, v in obj.items()
        }
    return _strip_quotes(obj)


class Controller:
    def __init__(
        self,
        lua_script_manager: "LuaScriptManager",
        game_state: "FactorioNamespace",
        *args,
        **kwargs,
    ):
        self.connection = lua_script_manager
        self.game_state = game_state
        self.name = self.camel_to_snake(self.__class__.__name__)
        self.lua_script_manager = lua_script_manager
        self.player_index = (
            game_state.agent_index + 1
        )  # +1 because Factorio is 1-indexed

    def clean_response(self, response):
        def is_lua_list(d):
            """Check if dictionary represents a Lua-style list (keys are consecutive numbers from 1)"""
            if not isinstance(d, dict) or not d:
                return False
            keys = set(str(k) for k in d.keys())
            return all(str(i) in keys for i in range(1, len(d) + 1))

        def clean_value(value):
            """Recursively clean a value"""
            if isinstance(value, dict):
                # Handle Lua-style lists
                if is_lua_list(value):
                    # Sort by numeric key and take only the values
                    sorted_items = sorted(value.items(), key=lambda x: int(str(x[0])))
                    return [clean_value(v) for k, v in sorted_items]

                # Handle inventory special case
                if any(isinstance(k, int) for k in value.keys()) and all(
                    isinstance(v, dict) and "name" in v and "count" in v
                    for v in value.values()
                ):
                    cleaned_dict = {}
                    for v in value.values():
                        cleaned_dict[v["name"]] = v["count"]
                    return cleaned_dict

                # Regular dictionary
                return {k: clean_value(v) for k, v in value.items()}

            elif isinstance(value, list):
                return [clean_value(v) for v in value]

            return value

        cleaned_response = {}

        if not hasattr(response, "items"):
            pass

        for key, value in response.items():
            if key == "direction":
                if isinstance(value, str):
                    cleaned_response[key] = Direction.from_string(value)
                elif isinstance(value, (int, float)):
                    dir_val = int(value)
                    # Factorio 2.0 uses direction values 0,4,8,12 which match our Direction enum
                    # No conversion needed - pass through directly
                    try:
                        cleaned_response[key] = Direction(dir_val)
                    except ValueError:
                        cleaned_response[key] = dir_val
                    continue
            elif not value and key in (
                "warnings",
                "input_connection_points",
                "output_connection_points",
            ):
                cleaned_response[key] = []
            else:
                cleaned_response[key] = clean_value(value)

        return cleaned_response

    def parse_lua_dict(self, d):
        if isinstance(d, (int, str, float)):
            return d

        # Handle lists that were already converted from integer-keyed dicts
        if isinstance(d, list):
            return [self.parse_lua_dict(item) for item in d]

        if isinstance(d, dict) and all(isinstance(k, int) for k in d.keys()):
            # Convert to list if all keys are numeric
            return [self.parse_lua_dict(d[k]) for k in sorted(d.keys())]
        else:
            # Process dictionaries with mixed keys
            new_dict = {}
            last_key = None

            for key in d.keys():
                if isinstance(key, int):
                    if last_key is not None and isinstance(d[key], str):
                        # Concatenate the value to the previous key's value
                        new_dict[last_key] += "-" + d[key]
                else:
                    last_key = key
                    if isinstance(d[key], dict):
                        # Recursively process nested dictionaries
                        new_dict[key] = self.parse_lua_dict(d[key])
                    else:
                        new_dict[key] = d[key]

            return new_dict

    def camel_to_snake(self, camel_str):
        snake_str = ""
        for index, char in enumerate(camel_str):
            if char.isupper():
                if index != 0:
                    snake_str += "_"
                snake_str += char.lower()
            else:
                snake_str += char
        return snake_str

    def _check_for_processing_error(self, lua_response: str) -> bool:
        """Check if the RCON response indicates a [processing] error"""
        if lua_response and "[processing]" in lua_response.lower():
            return True
        return False

    def _execute_once(self, *args) -> Tuple[Dict, str]:
        """Execute a single command attempt, returns (parsed payload, raw response).

        The parsed payload is {"a": <pcall ok>, "b": <result>} or None when the
        response could not be decoded.
        """
        start = time.time()
        parameters = [lua.encode(arg) for arg in args]
        invocation = f"pcall(storage.actions.{self.name}{(', ' if parameters else '') + ','.join(parameters)})"
        wrapped = f"{COMMAND} local a, b = {invocation}; rcon.print(encode_result(a, b))"
        lua_response = self.connection.rcon_client.send_command(wrapped)

        # Check for [processing] error from RCON layer
        if self._check_for_processing_error(lua_response):
            raise RconProcessingError("Game engine busy (processing), try again")

        if lua_response:
            idx = lua_response.find(JSON_PREFIX)
            if idx != -1:
                try:
                    payload = json.loads(lua_response[idx + len(JSON_PREFIX) :])
                except json.JSONDecodeError as e:
                    logger.warning("Malformed JSON envelope from %s: %s", self.name, e)
                    return None, lua_response

                b = payload.get("b")
                if b is None:
                    pass  # tool returned nil; leave "b" absent
                elif isinstance(b, str):
                    # Tools that return a JSON string (e.g. get_path,
                    # set_entity_recipe) historically had it decoded here with
                    # real lists preserved; plain strings just lose the
                    # serialize.lua quote wrapper.
                    s = _strip_quotes(b)
                    if s[:1] in "{[":
                        try:
                            payload["b"] = json.loads(s)
                        except json.JSONDecodeError:
                            payload["b"] = s
                    else:
                        payload["b"] = s
                else:
                    payload["b"] = _remove_numerical_keys(_luaify(b))
                return payload, lua_response

        # Legacy fallback: response did not come through encode_result (e.g.
        # game scripts that print directly). Parse as a Lua literal.
        parsed, _ = _lua2python(invocation, lua_response, start=start)
        return parsed, lua_response

    def execute(self, *args) -> Tuple[Dict, Any]:
        for attempt in range(MAX_PROCESSING_RETRIES):
            try:
                parsed, lua_response = self._execute_once(*args)
            except RconProcessingError:
                if attempt < MAX_PROCESSING_RETRIES - 1:
                    time.sleep(PROCESSING_RETRY_DELAY)
                continue
            except Exception as e:
                logger.warning("Tool %s failed to execute: %s", self.name, e)
                return {}, -1

            if parsed is None:
                return {}, lua_response

            result = parsed.get("b", {}) if isinstance(parsed, dict) else parsed

            if (
                isinstance(parsed, dict)
                and not parsed.get("a")
                and isinstance(result, str)
            ):
                # pcall failed: result is the error message
                if "[processing]" in result.lower():
                    if attempt < MAX_PROCESSING_RETRIES - 1:
                        time.sleep(PROCESSING_RETRY_DELAY)
                    continue
                return result, lua_response

            return result, lua_response

        # All retries exhausted
        return (
            "Game engine busy - command could not be executed after multiple retries",
            -1,
        )
