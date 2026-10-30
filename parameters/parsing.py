"""Discovery, validation and override of ``@PARAM`` parameters in managed scripts.

A managed script can expose editable parameters by marking module level variable
assignments with an ``@PARAM`` comment::

    # @PARAM
    copies = 3

    # @PARAM: Name used for the generated collection
    collection_name = "Generated"

    use_modifiers = True  # @PARAM

Only plain scalar literals can be exported: ``str``, ``int``, ``float`` and
``bool``.  Anything else (lists, dicts, tuples, ``None``, objects, function
calls, expressions) is reported back to the user as a validation error instead
of being silently ignored.

This module deliberately does not import ``bpy`` so it can be exercised outside
of Blender.
"""

from __future__ import annotations

import ast
import io
import math
import re
import tokenize
from dataclasses import dataclass, field
from typing import Any

# Matches an ``@PARAM`` marker inside a comment token, with an optional
# ``: description`` suffix.
_MARKER_RE = re.compile(r"^#\s*@PARAM\b\s*(?::\s*(?P<desc>.*?))?\s*$")

TYPE_BOOL = "BOOL"
TYPE_INT = "INT"
TYPE_FLOAT = "FLOAT"
TYPE_STRING = "STRING"

#: Parameter types that can be edited from the sidebar.
ALLOWED_TYPES = (TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING)

_PY_TO_PARAM = {
    bool: TYPE_BOOL,
    int: TYPE_INT,
    float: TYPE_FLOAT,
    str: TYPE_STRING,
}

_PARAM_TO_PY = {
    TYPE_BOOL: bool,
    TYPE_INT: int,
    TYPE_FLOAT: float,
    TYPE_STRING: str,
}

_ANNOTATION_TO_PARAM = {
    "bool": TYPE_BOOL,
    "int": TYPE_INT,
    "float": TYPE_FLOAT,
    "str": TYPE_STRING,
}

_SUPPORTED_TEXT = "only str, int, float and bool are supported"


@dataclass
class ExportedParameter:
    """One ``@PARAM`` marked variable found in a script."""

    name: str
    type: str = ""
    value: Any = None
    description: str = ""
    line: int = 0
    valid: bool = True
    error: str = ""
    #: Non-blocking problem, e.g. the variable is assigned again further down.
    warning: str = ""
    #: ``(lineno, col_offset, end_lineno, end_col_offset)`` of the value
    #: expression, used to rewrite it when overrides are applied.
    value_span: tuple | None = None


@dataclass
class _Marker:
    desc: str = ""
    standalone: bool = False


@dataclass
class _ScanResult:
    parameters: list = field(default_factory=list)
    errors: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Source helpers
# ---------------------------------------------------------------------------

def read_source(path):
    """Read a script from disk, normalising line endings to ``\\n``."""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def describe_read_error(exc):
    """User facing text for an exception raised by :func:`read_source`."""
    if isinstance(exc, UnicodeDecodeError):
        return "only UTF-8 encoded scripts are supported"
    return str(exc)


def _collect_comments(source):
    """Return ``(markers, comments)`` keyed by line number.

    ``tokenize`` is used rather than a plain regex so that ``@PARAM`` written
    inside a string literal is never mistaken for a marker.
    """
    markers = {}
    comments = {}
    lines = source.splitlines()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type != tokenize.COMMENT:
                continue
            lineno, col = tok.start
            line = lines[lineno - 1] if lineno - 1 < len(lines) else ""
            standalone = line[:col].strip() == ""
            match = _MARKER_RE.match(tok.string.strip())
            if match:
                markers[lineno] = _Marker((match.group("desc") or "").strip(), standalone)
            elif standalone:
                comments[lineno] = tok.string.lstrip("#").strip()
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # A malformed file is reported by ``ast.parse`` instead; whatever was
        # tokenised up to the failure is still usable.
        pass
    return markers, comments


def _node_end_line(node):
    return getattr(node, "end_lineno", None) or node.lineno


def _find_marker(node, markers, comments):
    """Locate the ``@PARAM`` marker attached to ``node``.

    Returns ``(marker_line, description)`` or ``(None, "")``.
    """
    start = node.lineno
    for lineno in range(start, _node_end_line(node) + 1):
        marker = markers.get(lineno)
        if marker is not None and not marker.standalone:
            return lineno, marker.desc

    # Walk upwards through the contiguous comment block above the statement.
    collected = []
    lineno = start - 1
    while lineno >= 1:
        marker = markers.get(lineno)
        if marker is not None and marker.standalone:
            desc = marker.desc or " ".join(reversed(collected))
            return lineno, desc.strip()
        comment = comments.get(lineno)
        if comment is None:
            break
        collected.append(comment)
        lineno -= 1
    return None, ""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _describe_node(node):
    try:
        return ast.unparse(node)
    except Exception:
        return "<expression>"


def _invalid(name, line, message, description=""):
    return ExportedParameter(
        name=name,
        line=line,
        valid=False,
        error=message,
        description=description,
    )


def _build_parameter(node, description):
    """Validate a single marked statement and turn it into a parameter."""
    line = node.lineno

    if isinstance(node, ast.AugAssign):
        return _invalid(
            _describe_node(node.target), line,
            "augmented assignment cannot be exported; assign a literal value instead",
            description,
        )

    if isinstance(node, ast.AnnAssign):
        target = node.target
        value = node.value
        annotation = node.annotation
    elif isinstance(node, ast.Assign):
        if len(node.targets) != 1:
            return _invalid(
                _describe_node(node.targets[0]), line,
                "chained assignment cannot be exported; export one variable per statement",
                description,
            )
        target = node.targets[0]
        value = node.value
        annotation = None
    else:
        return None

    if not isinstance(target, ast.Name):
        return _invalid(
            _describe_node(target), line,
            "only a plain variable name can be exported "
            "(no unpacking, attributes or subscripts)",
            description,
        )

    name = target.id

    if value is None:
        return _invalid(name, line, "an exported variable must be given a value", description)

    try:
        literal = ast.literal_eval(value)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return _invalid(
            name, line,
            f"value '{_describe_node(value)}' is not a literal; {_SUPPORTED_TEXT}",
            description,
        )

    param_type = _PY_TO_PARAM.get(type(literal))
    if param_type is None:
        return _invalid(
            name, line,
            f"type '{type(literal).__name__}' cannot be edited; {_SUPPORTED_TEXT}",
            description,
        )

    if annotation is not None:
        if not isinstance(annotation, ast.Name) or annotation.id not in _ANNOTATION_TO_PARAM:
            return _invalid(
                name, line,
                f"annotation '{_describe_node(annotation)}' is not an editable type; "
                f"{_SUPPORTED_TEXT}",
                description,
            )
        expected = _ANNOTATION_TO_PARAM[annotation.id]
        # ``x: float = 1`` is idiomatic Python, so widen int to float rather
        # than rejecting it.
        if expected == TYPE_FLOAT and param_type == TYPE_INT:
            literal = float(literal)
            param_type = TYPE_FLOAT
        elif expected != param_type:
            return _invalid(
                name, line,
                f"annotated as '{annotation.id}' but the value is "
                f"'{type(literal).__name__}'",
                description,
            )

    return ExportedParameter(
        name=name,
        type=param_type,
        value=literal,
        description=description,
        line=line,
        value_span=(
            value.lineno,
            value.col_offset,
            _node_end_line(value),
            value.end_col_offset,
        ),
    )


_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _module_stores(node):
    """Yield the ``ast.Name`` nodes ``node`` assigns in module scope.

    Function and class bodies are skipped: they have their own scope.
    """
    if isinstance(node, _SCOPE_NODES):
        return
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        yield node
    for child in ast.iter_child_nodes(node):
        yield from _module_stores(child)


def _find_reassignment(tree, param):
    """Line of the first module level assignment to ``param`` after its own."""
    for node in tree.body:
        if node.lineno <= param.line:
            continue
        for name in _module_stores(node):
            if name.id == param.name:
                return name.lineno
    return None


def parse_exported_parameters(source):
    """Scan ``source`` for ``@PARAM`` parameters.

    Returns ``(parameters, errors)`` where ``parameters`` includes entries that
    failed validation (``valid`` is ``False`` and ``error`` explains why), and
    ``errors`` holds file level problems such as a syntax error or a marker
    that is not attached to an assignment.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [], [f"Line {exc.lineno or 0}: syntax error - {exc.msg}"]
    except (ValueError, MemoryError, RecursionError) as exc:
        return [], [f"Could not parse script: {exc}"]

    markers, comments = _collect_comments(source)
    parameters = []
    consumed = set()
    seen = {}

    for node in tree.body:
        marker_line, description = _find_marker(node, markers, comments)
        if marker_line is None:
            continue

        param = _build_parameter(node, description)
        if param is None:
            # Attached to something that is not an assignment (a def, an
            # import, ...); left unconsumed so it is reported as an error.
            continue
        consumed.add(marker_line)

        if param.name in seen:
            param = _invalid(
                param.name, param.line,
                f"duplicate parameter; '{param.name}' is already exported on "
                f"line {seen[param.name]}",
                param.description,
            )
        else:
            seen[param.name] = param.line
            reassigned = _find_reassignment(tree, param)
            if reassigned is not None:
                param.warning = (
                    f"reassigned on line {reassigned}; the edited value is "
                    "overwritten there"
                )
        parameters.append(param)

    errors = [
        f"Line {lineno}: @PARAM must sit directly above (or at the end of) a "
        "module level variable assignment"
        for lineno in sorted(set(markers) - consumed)
    ]
    return parameters, errors


# ---------------------------------------------------------------------------
# Value coercion and override rewriting
# ---------------------------------------------------------------------------

def coerce_value(param_type, value):
    """Coerce ``value`` to ``param_type``, or return ``None`` if impossible."""
    py_type = _PARAM_TO_PY.get(param_type)
    if py_type is None:
        return None
    if type(value) is py_type:
        return value
    if py_type is bool:
        return bool(value) if isinstance(value, (bool, int, float)) else None
    if py_type is str:
        return value if isinstance(value, str) else None
    if isinstance(value, bool):
        # ``True`` is an ``int`` in Python; refuse the silent conversion.
        return None
    if py_type is int and isinstance(value, int):
        return int(value)
    if py_type is float and isinstance(value, (int, float)):
        return float(value)
    return None


def value_to_literal(value):
    """Render ``value`` as source text that evaluates back to it."""
    if isinstance(value, float) and not math.isfinite(value):
        return f"float({str(value)!r})"
    return repr(value)


def _line_start_offsets(data):
    offsets = [0]
    start = 0
    while True:
        index = data.find(b"\n", start)
        if index < 0:
            break
        offsets.append(index + 1)
        start = index + 1
    return offsets


def apply_overrides(source, overrides):
    """Return ``(new_source, applied_names)`` with ``overrides`` substituted in.

    ``overrides`` maps a parameter name to its new value.  Only valid, exported
    parameters are touched and the rewrite is purely textual, so everything
    else in the script - comments, formatting, unrelated code - is preserved
    byte for byte.  The script file on disk is never modified by this function.
    """
    if not overrides:
        return source, []

    parameters, _errors = parse_exported_parameters(source)
    replacements = []
    applied = []

    for param in parameters:
        if not param.valid or param.value_span is None:
            continue
        if param.name not in overrides:
            continue
        new_value = coerce_value(param.type, overrides[param.name])
        if new_value is None:
            continue
        replacements.append((param.value_span, value_to_literal(new_value)))
        applied.append(param.name)

    if not replacements:
        return source, []
    return _splice(source, replacements), applied


def _splice(source, edits):
    """Replace each ``(lineno, col, end_lineno, end_col)`` span with its text.

    A span with equal start and end inserts the text at that position.
    """
    data = source.encode("utf-8")
    # ``ast`` column offsets are byte offsets into the UTF-8 encoded line, so
    # the splice is done on bytes to stay correct for non-ASCII sources.
    starts = _line_start_offsets(data)
    spans = []
    for (lineno, col, end_lineno, end_col), text in edits:
        if lineno - 1 >= len(starts) or end_lineno - 1 >= len(starts):
            continue
        spans.append((starts[lineno - 1] + col, starts[end_lineno - 1] + end_col, text))

    for start, end, text in sorted(spans, key=lambda item: item[0], reverse=True):
        data = data[:start] + text.encode("utf-8") + data[end:]

    return data.decode("utf-8")


_COMPOUND_STATEMENTS = tuple(
    getattr(ast, name)
    for name in (
        "FunctionDef", "AsyncFunctionDef", "ClassDef", "If", "For", "AsyncFor",
        "While", "With", "AsyncWith", "Try", "TryStar", "Match",
    )
    if hasattr(ast, name)
)


def _is_docstring(node):
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_future_import(node):
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def inject_file_path(source, path):
    """Return ``source`` with ``__file__`` set to ``path`` before any other code.

    A patched copy runs from a temporary folder, so without this the script
    would see the copy's path and fail to find files next to the original.
    The assignment is added to an existing line, so line numbers reported in
    tracebacks still match the original file.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return source
    if not tree.body:
        return source

    assignment = f"__file__ = {value_to_literal(path)}"

    # The docstring and ``from __future__`` imports must stay first.
    header = None
    for index, node in enumerate(tree.body):
        if (index == 0 and _is_docstring(node)) or _is_future_import(node):
            header = node
        else:
            break
    if header is not None:
        end = (_node_end_line(header), header.end_col_offset)
        return _splice(source, [(end + end, f"; {assignment}")])

    first = tree.body[0]
    if not isinstance(first, _COMPOUND_STATEMENTS):
        start = (first.lineno, first.col_offset)
        return _splice(source, [(start + start, f"{assignment}; ")])

    # A compound statement cannot share its line, so this rare case (no
    # docstring, the file opens with a def, class, if, ...) gets a line of
    # its own and its line numbers shift by one.
    return f"{assignment}\n{source}"
