# Local override: do not let PyInstaller exclude `tkinter` just because
# its build-time Tcl/Tk probe fails. We bundle Tcl/Tk data explicitly in
# `CodexSwitch.spec`, and runtime hooks will point `TCL_LIBRARY` and
# `TK_LIBRARY` at the extracted bundle contents.


def pre_find_module_path(hook_api):
    return
