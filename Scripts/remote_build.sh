#!/usr/bin/env bash
#
# remote_build_run.sh
# Copies a source file to a Windows VM over SSH, compiles it, runs it,
# and prints the program's output back on the Linux host.
#
# Usage:
#   ./remote_build_run.sh <local_src_file> -o <output_name>
#
# Example:
#   ./remote_build_run.sh ./hello.c -o hello
#     -> copies hello.c to the VM, compiles to hello.exe, runs it
#
# Requirements on the Windows VM:
#   - OpenSSH Server enabled
#   - gcc (MinGW) on PATH
#
# Requirements on the Linux host:
#   - ssh and scp clients, key-based auth recommended

set -uo pipefail  # note: NOT -e, since we want to catch failures ourselves and report them

# ---- Config (edit to match your environment) ---------------------------
REMOTE_USER="winuser"
REMOTE_HOST="192.168.1.50"
REMOTE_DIR="C:/Users/${REMOTE_USER}/build"
SSH_KEY=""     # e.g. "-i ~/.ssh/id_ed25519", leave empty to use default
# ------------------------------------------------------------------------

SCRIPT_NAME="$(basename "$0")"

usage() {
    echo "Usage: ${SCRIPT_NAME} <local_src_file> -o <output_name>" >&2
    echo "  <local_src_file>   path to the source file to copy and compile" >&2
    echo "  -o <output_name>   base name for the remote source file and exe" >&2
    echo "                     (extension is taken from local_src_file)" >&2
    exit 1
}

die() {
    echo "[ERROR] $*" >&2
    exit 1
}

# ---- Parse arguments ----------------------------------------------------
LOCAL_FILE=""
OUTPUT_NAME=""

if [[ $# -lt 1 ]]; then
    usage
fi

LOCAL_FILE="$1"
shift

# Guard against the positional arg accidentally being an option
if [[ "${LOCAL_FILE}" == -* ]]; then
    die "First argument must be the source file path, got '${LOCAL_FILE}'"
fi

while getopts ":o:" opt; do
    case "${opt}" in
        o)
            OUTPUT_NAME="${OPTARG}"
            ;;
        :)
            die "Option -${OPTARG} requires an argument"
            ;;
        \?)
            die "Unknown option: -${OPTARG}"
            ;;
    esac
done

[[ -z "${OUTPUT_NAME}" ]] && { echo "[ERROR] -o <output_name> is required" >&2; usage; }

# ---- Validate local file -------------------------------------------------
[[ -f "${LOCAL_FILE}" ]] || die "Local file not found: ${LOCAL_FILE}"
[[ -r "${LOCAL_FILE}" ]] || die "Local file not readable: ${LOCAL_FILE}"

# Derive extension from the source file so we compile the right thing
EXT="${LOCAL_FILE##*.}"
if [[ "${EXT}" == "${LOCAL_FILE}" ]]; then
    die "Source file '${LOCAL_FILE}' has no extension; can't determine compiler"
fi

REMOTE_SRC_NAME="${OUTPUT_NAME}.${EXT}"
REMOTE_EXE_NAME="${OUTPUT_NAME}.exe"

SSH_OPTS=(${SSH_KEY} -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=10)
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"

run_ssh() {
    ssh "${SSH_OPTS[@]}" "${REMOTE}" "$@"
}

# ---- Step 1: connectivity check ------------------------------------------
echo "[*] Checking SSH connectivity to ${REMOTE}..."
if ! run_ssh "echo ok" >/dev/null 2>&1; then
    die "Could not connect to ${REMOTE} via SSH. Check host, credentials, and that OpenSSH Server is running."
fi

# ---- Step 2: ensure remote build dir exists -------------------------------
echo "[*] Ensuring remote build directory exists..."
if ! run_ssh "if not exist \"${REMOTE_DIR}\" mkdir \"${REMOTE_DIR}\""; then
    die "Failed to create/access remote directory: ${REMOTE_DIR}"
fi

# ---- Step 3: copy file -----------------------------------------------------
echo "[*] Copying ${LOCAL_FILE} to ${REMOTE}:${REMOTE_DIR}/${REMOTE_SRC_NAME}..."
if ! scp ${SSH_KEY} -o StrictHostKeyChecking=accept-new "${LOCAL_FILE}" \
        "${REMOTE}:${REMOTE_DIR}/${REMOTE_SRC_NAME}"; then
    die "scp failed while copying ${LOCAL_FILE} to remote host"
fi

# ---- Step 4: compile --------------------------------------------------------
echo "[*] Compiling on the Windows VM (${REMOTE_SRC_NAME} -> ${REMOTE_EXE_NAME})..."
COMPILE_OUTPUT=$(run_ssh "cd /d \"${REMOTE_DIR}\" && gcc \"${REMOTE_SRC_NAME}\" -o \"${REMOTE_EXE_NAME}\" 2>&1")
COMPILE_STATUS=$?

if [[ ${COMPILE_STATUS} -ne 0 ]]; then
    echo "[ERROR] Compilation failed (exit code ${COMPILE_STATUS}):" >&2
    echo "${COMPILE_OUTPUT}" >&2
    exit 1
fi
echo "[*] Compilation succeeded."

# ---- Step 5: run the program -------------------------------------------------
echo "[*] Running ${REMOTE_EXE_NAME}..."
PROGRAM_OUTPUT=$(run_ssh "cd /d \"${REMOTE_DIR}\" && \"${REMOTE_EXE_NAME}\"" 2>&1)
PROGRAM_STATUS=$?

echo "[*] Program exited with status ${PROGRAM_STATUS}"
echo "[*] Program output:"
echo "${PROGRAM_OUTPUT}"

exit ${PROGRAM_STATUS}
