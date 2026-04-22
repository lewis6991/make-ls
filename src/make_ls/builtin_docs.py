from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BuiltinKind = Literal["directive", "function", "target", "variable"]


@dataclass(frozen=True, slots=True)
class BuiltinDoc:
    kind: BuiltinKind
    signature: str
    summary: str


DIRECTIVE_DOCS: dict[str, BuiltinDoc] = {
    "-include": BuiltinDoc(
        kind="directive",
        signature="-include filenames...",
        summary="Read each listed makefile, but do not treat missing files as an error.",
    ),
    "define": BuiltinDoc(
        kind="directive",
        signature="define variable",
        summary="Start a multi-line variable definition that continues until `endef`.",
    ),
    "else": BuiltinDoc(
        kind="directive",
        signature="else",
        summary=(
            "Start the alternate branch of a conditional; `else ifeq` and similar "
            "forms chain another test."
        ),
    ),
    "endef": BuiltinDoc(
        kind="directive",
        signature="endef",
        summary="End a multi-line variable definition started by `define`.",
    ),
    "endif": BuiltinDoc(
        kind="directive",
        signature="endif",
        summary="End a conditional started by `ifeq`, `ifneq`, `ifdef`, or `ifndef`.",
    ),
    "export": BuiltinDoc(
        kind="directive",
        signature="export variable ...",
        summary="Export variables to the environment used for recipe commands.",
    ),
    "ifdef": BuiltinDoc(
        kind="directive",
        signature="ifdef variable-name",
        summary=(
            "Conditionally include the following text if the named variable expands "
            "to a non-empty value."
        ),
    ),
    "ifeq": BuiltinDoc(
        kind="directive",
        signature="ifeq (arg1, arg2)",
        summary="Conditionally include the following text if the two expanded arguments are equal.",
    ),
    "ifndef": BuiltinDoc(
        kind="directive",
        signature="ifndef variable-name",
        summary=(
            "Conditionally include the following text if the named variable expands "
            "to an empty value."
        ),
    ),
    "ifneq": BuiltinDoc(
        kind="directive",
        signature="ifneq (arg1, arg2)",
        summary=(
            "Conditionally include the following text if the two expanded arguments are not equal."
        ),
    ),
    "include": BuiltinDoc(
        kind="directive",
        signature="include filenames...",
        summary="Suspend reading the current makefile, read the listed makefiles, then continue.",
    ),
    "override": BuiltinDoc(
        kind="directive",
        signature="override variable = value",
        summary="Set or append to a variable even if it was set on the command line.",
    ),
    "private": BuiltinDoc(
        kind="directive",
        signature="private variable = value",
        summary="Keep a variable setting from being inherited by prerequisites.",
    ),
    "sinclude": BuiltinDoc(
        kind="directive",
        signature="sinclude filenames...",
        summary="Synonym for `-include`.",
    ),
    "undefine": BuiltinDoc(
        kind="directive",
        signature="undefine variable",
        summary="Undefine a variable so it behaves as though it had never been set.",
    ),
    "unexport": BuiltinDoc(
        kind="directive",
        signature="unexport variable ...",
        summary="Stop exporting the listed variables to the environment used for recipe commands.",
    ),
    "vpath": BuiltinDoc(
        kind="directive",
        signature="vpath pattern directories",
        summary="Set or clear directory search paths for prerequisites matching a pattern.",
    ),
}

FUNCTION_DOCS: dict[str, BuiltinDoc] = {
    "abspath": BuiltinDoc(
        kind="function",
        signature="$(abspath names...)",
        summary=(
            "Turn each name into an absolute path by removing `.` and `..` without "
            "resolving symlinks."
        ),
    ),
    "addprefix": BuiltinDoc(
        kind="function",
        signature="$(addprefix prefix,names...)",
        summary="Prepend the prefix to each whitespace-separated name.",
    ),
    "addsuffix": BuiltinDoc(
        kind="function",
        signature="$(addsuffix suffix,names...)",
        summary="Append the suffix to each whitespace-separated name.",
    ),
    "and": BuiltinDoc(
        kind="function",
        signature="$(and condition1,condition2,...)",
        summary=(
            "Expand each argument in order and return the last one if all are "
            "non-empty; otherwise return empty."
        ),
    ),
    "basename": BuiltinDoc(
        kind="function",
        signature="$(basename names...)",
        summary="Strip the final suffix from each file name.",
    ),
    "call": BuiltinDoc(
        kind="function",
        signature="$(call variable,param,...)",
        summary=(
            "Treat the value of a variable as a parameterized macro and expand it "
            "with positional arguments."
        ),
    ),
    "dir": BuiltinDoc(
        kind="function",
        signature="$(dir names...)",
        summary="Return the directory part of each file name; names without a slash yield `./`.",
    ),
    "error": BuiltinDoc(
        kind="function",
        signature="$(error text...)",
        summary="Stop `make` and report the expanded text as an error.",
    ),
    "eval": BuiltinDoc(
        kind="function",
        signature="$(eval text)",
        summary="Expand the text, then parse the result as makefile syntax.",
    ),
    "file": BuiltinDoc(
        kind="function",
        signature="$(file op filename,text)",
        summary="Write to, append to, or read from a file during expansion.",
    ),
    "filter": BuiltinDoc(
        kind="function",
        signature="$(filter pattern...,text)",
        summary="Keep the words in `text` that match any of the patterns.",
    ),
    "filter-out": BuiltinDoc(
        kind="function",
        signature="$(filter-out pattern...,text)",
        summary="Discard the words in `text` that match any of the patterns.",
    ),
    "findstring": BuiltinDoc(
        kind="function",
        signature="$(findstring find,in)",
        summary="Return `find` if it appears in `in`; otherwise return the empty string.",
    ),
    "firstword": BuiltinDoc(
        kind="function",
        signature="$(firstword names...)",
        summary="Return the first word in the expanded text.",
    ),
    "flavor": BuiltinDoc(
        kind="function",
        signature="$(flavor variable)",
        summary="Return the flavor of a variable, such as `recursive` or `simple`.",
    ),
    "foreach": BuiltinDoc(
        kind="function",
        signature="$(foreach var,list,text)",
        summary="Expand `text` once for each word in `list`, with `var` set to that word.",
    ),
    "if": BuiltinDoc(
        kind="function",
        signature="$(if condition,then[,else])",
        summary=(
            "Expand `then` if the condition is non-empty after expansion; otherwise "
            "expand `else` if provided."
        ),
    ),
    "join": BuiltinDoc(
        kind="function",
        signature="$(join list1,list2)",
        summary="Join the words in two lists pairwise.",
    ),
    "lastword": BuiltinDoc(
        kind="function",
        signature="$(lastword names...)",
        summary="Return the last word in the expanded text.",
    ),
    "notdir": BuiltinDoc(
        kind="function",
        signature="$(notdir names...)",
        summary="Return everything after the last slash in each file name.",
    ),
    "or": BuiltinDoc(
        kind="function",
        signature="$(or condition1,condition2,...)",
        summary="Expand each argument in order and return the first non-empty one.",
    ),
    "origin": BuiltinDoc(
        kind="function",
        signature="$(origin variable)",
        summary=(
            "Report where a variable came from, such as the environment, a makefile, "
            "or the command line."
        ),
    ),
    "patsubst": BuiltinDoc(
        kind="function",
        signature="$(patsubst pattern,replacement,text)",
        summary="Replace words in `text` that match the pattern.",
    ),
    "realpath": BuiltinDoc(
        kind="function",
        signature="$(realpath names...)",
        summary=(
            "Return the canonical absolute path for each name, resolving symlinks when possible."
        ),
    ),
    "shell": BuiltinDoc(
        kind="function",
        signature="$(shell command)",
        summary="Run a shell command and replace newlines in its output with spaces.",
    ),
    "sort": BuiltinDoc(
        kind="function",
        signature="$(sort list)",
        summary="Sort the words in the list and remove duplicates.",
    ),
    "strip": BuiltinDoc(
        kind="function",
        signature="$(strip string)",
        summary=(
            "Trim leading and trailing whitespace and collapse internal runs of "
            "whitespace to single spaces."
        ),
    ),
    "subst": BuiltinDoc(
        kind="function",
        signature="$(subst from,to,text)",
        summary="Replace every occurrence of `from` with `to` in `text`.",
    ),
    "suffix": BuiltinDoc(
        kind="function",
        signature="$(suffix names...)",
        summary="Return the suffix of each file name.",
    ),
    "value": BuiltinDoc(
        kind="function",
        signature="$(value variable)",
        summary="Return the unexpanded value of a variable.",
    ),
    "warning": BuiltinDoc(
        kind="function",
        signature="$(warning text...)",
        summary="Report the expanded text as a warning and continue.",
    ),
    "wildcard": BuiltinDoc(
        kind="function",
        signature="$(wildcard pattern...)",
        summary="Expand shell-style wildcard patterns to the list of matching existing files.",
    ),
    "word": BuiltinDoc(
        kind="function",
        signature="$(word n,text)",
        summary="Return word number `n` from the expanded text.",
    ),
    "wordlist": BuiltinDoc(
        kind="function",
        signature="$(wordlist s,e,text)",
        summary="Return words `s` through `e` from the expanded text.",
    ),
    "words": BuiltinDoc(
        kind="function",
        signature="$(words text)",
        summary="Count the number of words in the expanded text.",
    ),
}

BUILTIN_VARIABLE_DOCS: dict[str, BuiltinDoc] = {
    "MAKE": BuiltinDoc(
        kind="variable",
        signature="$(MAKE)",
        summary=(
            "The name with which `make` was invoked. In recipe lines containing "
            "`MAKE`, flags such as `-n`, `-t`, and `-q` do not suppress execution."
        ),
    ),
    "MAKEFILES": BuiltinDoc(
        kind="variable",
        signature="$(MAKEFILES)",
        summary="Names of makefiles to read on every invocation of `make`.",
    ),
    "MAKE_VERSION": BuiltinDoc(
        kind="variable",
        signature="$(MAKE_VERSION)",
        summary="Expands to the GNU Make version number.",
    ),
    "MAKE_HOST": BuiltinDoc(
        kind="variable",
        signature="$(MAKE_HOST)",
        summary="Expands to a string describing the host GNU Make was built to run on.",
    ),
    "MAKELEVEL": BuiltinDoc(
        kind="variable",
        signature="$(MAKELEVEL)",
        summary="The recursion depth of sub-`make` invocations.",
    ),
    "MAKEFLAGS": BuiltinDoc(
        kind="variable",
        signature="$(MAKEFLAGS)",
        summary=(
            "The flags given to `make`. In recipes, let recursive `make` inherit it "
            "through the environment instead of using it directly on the shell line."
        ),
    ),
    "MAKEOVERRIDES": BuiltinDoc(
        kind="variable",
        signature="$(MAKEOVERRIDES)",
        summary=(
            "Holds the command-line variable definitions that GNU Make references "
            "from `MAKEFLAGS` during recursive builds."
        ),
    ),
    "GNUMAKEFLAGS": BuiltinDoc(
        kind="variable",
        signature="$(GNUMAKEFLAGS)",
        summary="GNU Make-specific command-line flags parsed by `make`.",
    ),
    "MFLAGS": BuiltinDoc(
        kind="variable",
        signature="$(MFLAGS)",
        summary=(
            "Historical compatibility variable similar to `MAKEFLAGS`, but without "
            "command-line variable definitions and usually beginning with a hyphen."
        ),
    ),
    "MAKECMDGOALS": BuiltinDoc(
        kind="variable",
        signature="$(MAKECMDGOALS)",
        summary="The targets passed to `make` on the command line.",
    ),
    "CURDIR": BuiltinDoc(
        kind="variable",
        signature="$(CURDIR)",
        summary=(
            "The absolute pathname of the current working directory after `-C` "
            "options are processed."
        ),
    ),
    "VPATH": BuiltinDoc(
        kind="variable",
        signature="$(VPATH)",
        summary="Directory search path for files not found in the current directory.",
    ),
    "SHELL": BuiltinDoc(
        kind="variable",
        signature="$(SHELL)",
        summary="The shell used to run recipes, usually `/bin/sh` by default.",
    ),
    ".SHELLFLAGS": BuiltinDoc(
        kind="variable",
        signature="$(.SHELLFLAGS)",
        summary=(
            "Arguments passed to the shell used for recipes; defaults to `-c`, or "
            "`-ec` in POSIX-conforming mode."
        ),
    ),
    "MAKEFILE_LIST": BuiltinDoc(
        kind="variable",
        signature="$(MAKEFILE_LIST)",
        summary="Names of parsed makefiles, appended in the order `make` reads them.",
    ),
    ".DEFAULT_GOAL": BuiltinDoc(
        kind="variable",
        signature="$(.DEFAULT_GOAL)",
        summary=(
            "The current default goal. Clearing it restarts default-goal selection; "
            "setting it chooses an explicit default target."
        ),
    ),
    ".RECIPEPREFIX": BuiltinDoc(
        kind="variable",
        signature="$(.RECIPEPREFIX)",
        summary="The first character used to introduce recipe lines instead of a tab.",
    ),
    ".VARIABLES": BuiltinDoc(
        kind="variable",
        signature="$(.VARIABLES)",
        summary=(
            "A list of all global variables defined so far, including built-in "
            "variables. Assignments to it are ignored."
        ),
    ),
    ".FEATURES": BuiltinDoc(
        kind="variable",
        signature="$(.FEATURES)",
        summary="A list of special features supported by this version of GNU Make.",
    ),
    ".INCLUDE_DIRS": BuiltinDoc(
        kind="variable",
        signature="$(.INCLUDE_DIRS)",
        summary="Directories GNU Make searches for included makefiles.",
    ),
    ".EXTRA_PREREQS": BuiltinDoc(
        kind="variable",
        signature="$(.EXTRA_PREREQS)",
        summary=(
            "Extra prerequisites added to targets without showing up in automatic "
            "variables such as `$^`."
        ),
    ),
    ".LIBPATTERNS": BuiltinDoc(
        kind="variable",
        signature="$(.LIBPATTERNS)",
        summary="Controls the library name patterns `make` searches and their order.",
    ),
    "MAKE_RESTARTS": BuiltinDoc(
        kind="variable",
        signature="$(MAKE_RESTARTS)",
        summary="How many times this `make` instance has restarted after remaking makefiles.",
    ),
    "MAKE_TERMOUT": BuiltinDoc(
        kind="variable",
        signature="$(MAKE_TERMOUT)",
        summary="Set when GNU Make believes stdout is a terminal.",
    ),
    "MAKE_TERMERR": BuiltinDoc(
        kind="variable",
        signature="$(MAKE_TERMERR)",
        summary="Set when GNU Make believes stderr is a terminal.",
    ),
    "AR": BuiltinDoc(
        kind="variable",
        signature="$(AR)",
        summary=(
            "Built-in implicit-rule variable for the archive-maintaining program; default `ar`."
        ),
    ),
    "ARFLAGS": BuiltinDoc(
        kind="variable",
        signature="$(ARFLAGS)",
        summary="Extra flags for the archive-maintaining program; default `rv`.",
    ),
    "CC": BuiltinDoc(
        kind="variable",
        signature="$(CC)",
        summary="Built-in implicit-rule variable for the C compiler; default `cc`.",
    ),
    "CFLAGS": BuiltinDoc(
        kind="variable",
        signature="$(CFLAGS)",
        summary="Extra flags for the C compiler in built-in implicit rules.",
    ),
    "CPP": BuiltinDoc(
        kind="variable",
        signature="$(CPP)",
        summary="Built-in implicit-rule variable for the C preprocessor; default `$(CC) -E`.",
    ),
    "CPPFLAGS": BuiltinDoc(
        kind="variable",
        signature="$(CPPFLAGS)",
        summary="Extra flags for the C preprocessor and compilers that use it.",
    ),
    "CXX": BuiltinDoc(
        kind="variable",
        signature="$(CXX)",
        summary="Built-in implicit-rule variable for the C++ compiler; default `g++`.",
    ),
    "CXXFLAGS": BuiltinDoc(
        kind="variable",
        signature="$(CXXFLAGS)",
        summary="Extra flags for the C++ compiler in built-in implicit rules.",
    ),
    "LDFLAGS": BuiltinDoc(
        kind="variable",
        signature="$(LDFLAGS)",
        summary="Non-library flags passed when compilers invoke the linker, such as `-L`.",
    ),
    "LDLIBS": BuiltinDoc(
        kind="variable",
        signature="$(LDLIBS)",
        summary="Library flags or names passed when compilers invoke the linker.",
    ),
    "RM": BuiltinDoc(
        kind="variable",
        signature="$(RM)",
        summary="Built-in implicit-rule variable for removing files; default `rm -f`.",
    ),
}

SPECIAL_TARGET_DOCS: dict[str, BuiltinDoc] = {
    ".PHONY": BuiltinDoc(
        kind="target",
        signature=".PHONY: targets...",
        summary="Prerequisites are always treated as phony targets and run unconditionally.",
    ),
    ".SUFFIXES": BuiltinDoc(
        kind="target",
        signature=".SUFFIXES: suffixes...",
        summary="Defines the suffix list used for old-fashioned suffix rules.",
    ),
    ".DEFAULT": BuiltinDoc(
        kind="target",
        signature=".DEFAULT:",
        summary="Fallback recipe used when no explicit or implicit rule is found.",
    ),
    ".PRECIOUS": BuiltinDoc(
        kind="target",
        signature=".PRECIOUS: targets...",
        summary=(
            "Preserves listed targets from deletion on interruption and keeps intermediate files."
        ),
    ),
    ".INTERMEDIATE": BuiltinDoc(
        kind="target",
        signature=".INTERMEDIATE: targets...",
        summary="Treats listed targets as intermediate files.",
    ),
    ".NOTINTERMEDIATE": BuiltinDoc(
        kind="target",
        signature=".NOTINTERMEDIATE: targets...",
        summary="Prevents listed targets from being considered intermediate files.",
    ),
    ".SECONDARY": BuiltinDoc(
        kind="target",
        signature=".SECONDARY: targets...",
        summary="Marks listed targets as intermediate files that are never automatically deleted.",
    ),
    ".SECONDEXPANSION": BuiltinDoc(
        kind="target",
        signature=".SECONDEXPANSION:",
        summary="Enables a second expansion pass for prerequisite lists defined after it appears.",
    ),
    ".DELETE_ON_ERROR": BuiltinDoc(
        kind="target",
        signature=".DELETE_ON_ERROR:",
        summary="Deletes a changed target if its recipe exits with a nonzero status.",
    ),
    ".IGNORE": BuiltinDoc(
        kind="target",
        signature=".IGNORE: targets...",
        summary=(
            "Ignores recipe errors for listed targets, or for all targets if used "
            "without prerequisites."
        ),
    ),
    ".LOW_RESOLUTION_TIME": BuiltinDoc(
        kind="target",
        signature=".LOW_RESOLUTION_TIME: targets...",
        summary="Treats listed files as having low-resolution timestamps.",
    ),
    ".SILENT": BuiltinDoc(
        kind="target",
        signature=".SILENT: targets...",
        summary=(
            "Suppresses recipe echoing for listed targets, or for all targets if "
            "used without prerequisites."
        ),
    ),
    ".EXPORT_ALL_VARIABLES": BuiltinDoc(
        kind="target",
        signature=".EXPORT_ALL_VARIABLES:",
        summary="Exports all variables to child processes by default.",
    ),
    ".NOTPARALLEL": BuiltinDoc(
        kind="target",
        signature=".NOTPARALLEL: targets...",
        summary=(
            "Disables parallel execution globally, or serializes prerequisites of listed targets."
        ),
    ),
    ".ONESHELL": BuiltinDoc(
        kind="target",
        signature=".ONESHELL:",
        summary="Runs all recipe lines for a target in a single shell invocation.",
    ),
    ".POSIX": BuiltinDoc(
        kind="target",
        signature=".POSIX:",
        summary=(
            "Runs GNU Make in POSIX-conforming mode where its default behavior differs from POSIX."
        ),
    ),
}

_AUTOMATIC_VARIABLES = {
    "@": ("$@", "Automatic variable: file name of the target."),
    "%": ("$%", "Automatic variable: archive member name of the target, if any."),
    "<": ("$<", "Automatic variable: name of the first prerequisite."),
    "?": ("$?", "Automatic variable: prerequisites newer than the target."),
    "^": ("$^", "Automatic variable: all prerequisites, with duplicates removed."),
    "+": ("$+", "Automatic variable: all prerequisites, preserving duplicates and order."),
    "|": ("$|", "Automatic variable: all order-only prerequisites."),
    "*": ("$*", "Automatic variable: stem matched by an implicit or static pattern rule."),
}

for name, (signature, summary) in _AUTOMATIC_VARIABLES.items():
    BUILTIN_VARIABLE_DOCS[name] = BuiltinDoc(
        kind="variable",
        signature=signature,
        summary=summary,
    )
    BUILTIN_VARIABLE_DOCS[f"{name}D"] = BuiltinDoc(
        kind="variable",
        signature=f"$({name}D)",
        summary=f"Automatic variable: directory part of `{signature}`.",
    )
    BUILTIN_VARIABLE_DOCS[f"{name}F"] = BuiltinDoc(
        kind="variable",
        signature=f"$({name}F)",
        summary=f"Automatic variable: file-within-directory part of `{signature}`.",
    )
