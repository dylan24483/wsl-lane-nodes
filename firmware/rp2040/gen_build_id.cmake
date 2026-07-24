# Build-time wrapper for the deterministic identity generator.
#
# There is deliberately no Git/worktree inspection here. release_provenance.py
# hashes the explicit firmware source/recipe allowlist, image-affecting options,
# Pico SDK commit, and C compiler ID/version. Unrelated dirty files therefore
# cannot alter id.build, while a different toolchain cannot impersonate it.
#
# Required -D inputs:
#   SRC_DIR, OUT, PYTHON, VARIANT, DEBUG_USB, PICO_BOARD, BUILD_TYPE,
#   SDK_COMMIT, C_COMPILER_ID

foreach(REQUIRED SRC_DIR OUT PYTHON VARIANT DEBUG_USB PICO_BOARD BUILD_TYPE
                 SDK_COMMIT C_COMPILER_ID)
    if(NOT DEFINED ${REQUIRED} OR "${${REQUIRED}}" STREQUAL "")
        message(FATAL_ERROR "gen_build_id.cmake: missing -D${REQUIRED}")
    endif()
endforeach()

set(DEBUG_ARG)
if(DEBUG_USB)
    set(DEBUG_ARG --debug-usb)
endif()

execute_process(
    COMMAND "${PYTHON}" "${SRC_DIR}/release_provenance.py" write-header
            --source-dir "${SRC_DIR}"
            --variant "${VARIANT}"
            ${DEBUG_ARG}
            --pico-board "${PICO_BOARD}"
            --build-type "${BUILD_TYPE}"
            --sdk-commit "${SDK_COMMIT}"
            --compiler-id "${C_COMPILER_ID}"
            --output "${OUT}"
    RESULT_VARIABLE IDENTITY_RC
    OUTPUT_VARIABLE IDENTITY_STDOUT
    ERROR_VARIABLE IDENTITY_STDERR
)
if(NOT IDENTITY_RC EQUAL 0)
    message(FATAL_ERROR
        "deterministic firmware identity generation failed (${IDENTITY_RC})\n"
        "${IDENTITY_STDOUT}${IDENTITY_STDERR}")
endif()
