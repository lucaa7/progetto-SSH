import re

DEVICE_PROFILES = {
    "cisco": {
        "prompt_endings": ("#", ">"),
        "disable_paging_cmd": "terminal datadump",
        "use_shell": True, "term": "vt100",
    },
    "cisco_ios": {
        "prompt_endings": ("#", ">"),
        "disable_paging_cmd": "terminal length 0",
        "use_shell": True, "term": "vt100",
    },
    "mikrotik": {
        "prompt_endings": ("] > ", "] >"),
        "use_shell": False, "term": None, "disable_paging_cmd": None,
    },
    "generic": {
        "prompt_endings": ("#", ">", "$"),
        "disable_paging_cmd": None,
        "use_shell": True, "term": "vt100",
    },
}


