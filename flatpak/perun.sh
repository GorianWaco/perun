#!/bin/sh
export PYTHONPATH="/app/lib/perun${PYTHONPATH:+:$PYTHONPATH}"
exec python3 /app/lib/perun/perun.py "$@"
