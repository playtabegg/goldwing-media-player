"""Scripts. Not shipped - `pyproject` excludes `tools*` from the package.

There is an `__init__.py` here for one reason: rialto2 has a `tools` package
of its own, and a test that appends the factory to `sys.path` made `import
tools.theme_menu` resolve against theirs. A regular package on the path in
front wins outright; a namespace directory does not.
"""
