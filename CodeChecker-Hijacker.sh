#!/bin/bash

echo "This is a hacked CodeChecker wrapper that will drive 'multi pass Tidy'" >&2
echo "(\"CTU\") on projects. Please do NOT use this in production, this entire " >&2
echo "code is ridiculous!" >&2
echo "======================================================================" >&2

echo "We are '$0'..." >&2
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
CCH="$SCRIPT_DIR/__CodeChecker"
echo "Real CodeChecker available at '$CCH'" >&2
echo
echo

if [[ -z "$CCH" || ! -x "$CCH" ]]
then
  echo "FUCK! Real CodeChecker not available or not executable?" >&2
  exit 1
fi

if [[ $# -le 1 || "$1" != "analyze" ]]
then
  echo "I can't figure out what to do, let's just forward to CodeChecker..." >&2
  exec $CCH "$@"
fi

echo "'CodeChecker analyze' was called, this is the real deal now!" >&2
echo -e "Args:\n\t$@\n"

echo "Figuring out where Clang-Tidy is... " >&2
TIDYPATH=$($CCH analyzers --output table --details | \
  grep "clang-tidy" | \
  head -n 1 | \
  cut -d '|' -f 2 | \
  sed 's/ //g')
echo "$TIDYPATH" >&2

if [[ -z "$TIDYPATH" ]]
then
  echo "FUCK! CodeChecker doesn't know where 'clang-tidy' is?!" >&2
  exit 1
fi

echo
echo " - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - "
echo "            Executing with Tidy-Args for 'collect' phase..."
echo " - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - "
echo

args=("$@")
OUTPUT_DIR=""
OUTPUT_DIR_IDX_IN_ARGS=0
found_output_dir=0
for idx in "${!args[@]}"
do
  if [[ "${args[$idx]}" == "-o" || "${args[$idx]}" == "--output" ]]
  then
    echo "Found -o/--output flag!" >&2
    found_output_dir=1
    continue
  fi

  if [[ $found_output_dir -eq 1 ]]
  then
    echo -n "Analysis results are output to " >&2
    OUTPUT_DIR="$(readlink -f ${args[$idx]})"
    OUTPUT_DIR_IDX_IN_ARGS=$idx
    echo "'${OUTPUT_DIR}'" >&2
    found_output_dir=0
  fi
done
if [[ $OUTPUT_DIR_IDX_IN_ARGS -eq 0 ]]
then
  echo "FUCK! No '-o'/'--output' flag found...!" >&2
  exit 1
fi

echo
echo

TIDYARGS_DIR="$(readlink -f $(pwd))"
COLLECT_DIR="${OUTPUT_DIR}_Collect/MultiPassTidyRoot"

echo "--multipass-phase=collect --multipass-dir=\"${COLLECT_DIR}\"" > ${TIDYARGS_DIR}/collect.txt
echo "--multipass-phase=diagnose --multipass-dir=\"${COLLECT_DIR}\"" > ${TIDYARGS_DIR}/diagnose.txt

args[$OUTPUT_DIR_IDX_IN_ARGS]="${OUTPUT_DIR}_Collect"
collect_args=("${args[@]} --tidyargs ${TIDYARGS_DIR}/collect.txt")
echo "Executing analysis..." >&2
cat ${TIDYARGS_DIR}/collect.txt
echo -e "Args:\n\t${collect_args[@]}\n"

$CCH ${collect_args[@]}

echo
echo " - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - "
echo "            Executing with Tidy-Args for 'compact' phase..."
echo " - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - "
echo

ls -alh ${COLLECT_DIR}

${TIDYPATH} --checks='*' --multipass-phase=compact --multipass-dir="${COLLECT_DIR}"

echo
echo " - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - "
echo "            Executing with Tidy-Args for 'diagnose' phase..."
echo " - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - "
echo

ls -alh ${COLLECT_DIR}

args[$OUTPUT_DIR_IDX_IN_ARGS]="${OUTPUT_DIR}"
diagnose_args=("${args[@]} --tidyargs ${TIDYARGS_DIR}/diagnose.txt")
echo "Executing analysis..." >&2
cat ${TIDYARGS_DIR}/diagnose.txt
echo -e "Args:\n\t${diagnose_args[@]}\n"

$CCH ${diagnose_args[@]}
