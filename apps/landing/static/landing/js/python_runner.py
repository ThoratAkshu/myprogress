"""Runs practice code: in the browser under Pyodide (python-worker.js loads this file), and in the server's tests.

run() executes the code with print captured. With trace on, it records every line about to run, the variables in
scope, the call stack and the output so far: the steps of the dry run. Challenge tests are evaluated afterwards. A step
limit stops loops that never end. Only a person's own code runs, in their own browser."""
import ast
import io
import json
import sys

FILENAME = "<practice>"


class StepLimit(Exception):
    pass


def show(value):
    """A short, readable value for the variables panel."""
    try:
        if isinstance(value, type):
            return f"class {value.__name__}"
        if callable(value) and hasattr(value, "__name__"):
            return f"function {value.__name__}"
        text = repr(value)
    except Exception:
        text = f"<{type(value).__name__}>"
    return text if len(text) <= 80 else text[:77] + "..."


def frame_vars(frame):
    names = {}
    for name, value in frame.f_locals.items():
        if name.startswith("__") or name == "input" or type(value).__name__ == "module":
            continue
        names[name] = show(value)
    return names


def stack_of(frame):
    names = []
    while frame is not None:
        if frame.f_code.co_filename == FILENAME:
            names.append("main" if frame.f_code.co_name == "<module>" else frame.f_code.co_name)
        frame = frame.f_back
    return names[::-1]


def no_input(*args):
    raise RuntimeError("input() can't ask you anything here. Put the value in your code instead.")


def error_line(error):
    line = None
    trace = error.__traceback__
    while trace is not None:
        if trace.tb_frame.f_code.co_filename == FILENAME:
            line = trace.tb_lineno
        trace = trace.tb_next
    return line


def run(code, trace=False, limit=200000, tests="[]"):
    output = io.StringIO()
    steps = []
    count = [0]

    def tracer(frame, event, arg):
        if frame.f_code.co_filename != FILENAME:
            return None
        if event == "line":
            count[0] += 1
            if count[0] > limit:
                raise StepLimit()
            if trace:
                steps.append({"line": frame.f_lineno, "vars": frame_vars(frame), "stack": stack_of(frame), "out": output.getvalue()})
        return tracer

    scope = {"__name__": "__main__", "input": no_input}
    error, results = None, []
    saved = sys.stdout
    sys.stdout = output
    try:
        compiled = compile(code, FILENAME, "exec")
        sys.settrace(tracer)
        exec(compiled, scope)
        for test in json.loads(tests):
            try:
                got = eval(test["call"], scope)
                results.append({"call": test["call"], "expected": test["expected"], "got": show(got), "passed": got == ast.literal_eval(test["expected"])})
            except StepLimit:
                raise
            except Exception as failure:
                results.append({"call": test["call"], "expected": test["expected"], "got": f"{type(failure).__name__}: {failure}", "passed": False})
    except StepLimit:
        error = {"line": None, "message": f"Stopped after {limit:,} steps. Is there a loop that never ends?"}
    except SyntaxError as failure:
        error = {"line": failure.lineno, "message": f"SyntaxError: {failure.msg}"}
    except Exception as failure:
        error = {"line": error_line(failure), "message": f"{type(failure).__name__}: {failure}"}
    finally:
        sys.settrace(None)
        sys.stdout = saved
    if trace and not error:
        final = {name: show(value) for name, value in scope.items() if not name.startswith("__") and name != "input" and type(value).__name__ != "module"}
        steps.append({"line": None, "vars": final, "stack": [], "out": output.getvalue(), "done": True})
    return json.dumps({"output": output.getvalue(), "steps": steps, "error": error, "tests": results})
