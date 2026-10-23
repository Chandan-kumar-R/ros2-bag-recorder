"""
Pure topic-selection logic: registry validation and topic matching.
"""
import re


class RegistryError(ValueError):
    """Raised when the topic registry or a pattern list is malformed."""


def compile_patterns(patterns, where='exclude_patterns'):
    """Compile a list of regex strings; raise RegistryError on a bad one."""
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as err:
            raise RegistryError(f"Bad regex '{pattern}' in {where}: {err}") from err
    return compiled


def compile_keywords(keywords):
    """
    Compile plain keywords into substring-match patterns.

    Each keyword matches any topic name that contains it as a literal substring. Returns a list of compiled regexes.
    """
    return [re.compile(f'.*{re.escape(keyword)}.*') for keyword in keywords]


def load_enabled_entries(registry, enabled_modules):
    """
    Collect selectors from the enabled modules of a topic registry.

    Raises RegistryError on any malformed entry.
    """
    if not isinstance(registry, dict):
        raise RegistryError('Registry root must be a mapping of modules.')
    exact, patterns = set(), []
    for module, entries in registry.items():
        if module not in enabled_modules:
            continue
        if not isinstance(entries, list):
            raise RegistryError(f"Module '{module}': must be a list of entries.")
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or len(entry) != 1:
                raise RegistryError(
                    f"Module '{module}' entry {index}: needs exactly one of "
                    "'topic' or 'pattern'.")
            key, value = next(iter(entry.items()))
            if key == 'topic':
                exact.add(value)
            elif key == 'pattern':
                patterns.extend(
                    compile_patterns([value], where=f"module '{module}' entry {index}"))
            else:
                raise RegistryError(
                    f"Module '{module}' entry {index}: unknown key '{key}' "
                    "(use 'topic' or 'pattern').")
    return exact, patterns


def match_topics(live_topics, exact_names, include_patterns, exclude_patterns):
    """
    Select topics from live_topics.

    A topic is selected if it is an exact name or fullmatches any include
    pattern, and does not fullmatch any exclude pattern (excludes win).
    """
    matched = set()
    for name in live_topics:
        included = name in exact_names or any(
            p.fullmatch(name) for p in include_patterns)
        excluded = any(p.fullmatch(name) for p in exclude_patterns)
        if included and not excluded:
            matched.add(name)
    return matched
