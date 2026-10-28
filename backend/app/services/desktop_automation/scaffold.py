"""Translate recorded actions mechanically; Agents only author business calculations."""

from .code_contracts import PythonScript
from .contracts import PARAMETER, Script


def python_template(script: Script) -> dict:
    def expression(text: str) -> str:
        refs = list(PARAMETER.finditer(text))
        if not refs:
            return repr(text)
        if any(m.group(1) in script.secret_parameters for m in refs) and not (
            len(refs) == 1 and refs[0].span() == (0, len(text))
        ):
            raise ValueError("Mixed secret interpolation needs manual conversion to a direct ui.type_text input")
        parts, position = [], 0
        for match in refs:
            if match.start() > position:
                parts.append(repr(text[position : match.start()]))
            parts.append("inputs[" + repr(match.group(1)) + "]")
            position = match.end()
        if position < len(text):
            parts.append(repr(text[position:]))
        return " + ".join(parts)

    lines = [
        "from automation import ui, inputs",
        "",
        "# Replace parameter calculations above the action sequence; preserve verified window targets and clicks.",
    ]
    windows = {}
    for step in script.steps:
        if step.action == "launch_app":
            lines.append(f"ui.launch({step.app!r}, label={step.label!r})")
            continue
        if step.target is None:
            raise ValueError("Every non-launch action needs a recorded window target before generating Python")
        key = (step.target.app, step.target.title)
        if key not in windows:
            var = "w" + str(len(windows) + 1)
            windows[key] = var
            lines.append(f"{var} = ui.window({step.target.app!r}, {expression(step.target.title)})")
        args = f"target={windows[key]}, label={step.label!r}"
        if step.action in {"click", "double_click", "right_click"}:
            line = f"ui.{step.action}({step.x}, {step.y}, {args})"
        elif step.action == "type_text":
            line = f"ui.type_text({expression(step.text)}, {args})"
        elif step.action == "assert_text":
            line = f"ui.assert_text({expression(step.text)}, timeout_seconds={step.timeout_seconds}, {args})"
        elif step.action in {"press_key", "hotkey"}:
            line = f"ui.key({step.key!r}, modifiers={step.modifiers!r}, {args})"
        else:
            line = f"ui.scroll({step.direction!r}, {step.amount}, {args})"
        lines.append(line)
    source = "\n".join(lines) + "\n"
    if len(source.encode()) > 18000:
        raise ValueError("Recorded workflow exceeds the 18 KiB model template budget; use its paginated steps")
    return PythonScript(
        format="clawith.python.v1",
        source=source,
        parameters=script.parameters,
        secret_parameters=script.secret_parameters,
    ).model_dump()
