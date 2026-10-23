#!/usr/bin/env bash
# Weekly job: add new Project Synapse episodes, commit, and push to origin
# (only when something new was committed). The target branch is set by
# SYNAPSE_BRANCH (default: master); the job only runs when that branch is
# checked out, and refuses to run over uncommitted edits to the data files.
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
expected_branch="${SYNAPSE_BRANCH:-master}"
data_files=(episodes.json index.html)

cd "$repo_dir"

current_branch="$(git symbolic-ref --quiet --short HEAD || echo DETACHED)"
if [[ "$current_branch" != "$expected_branch" ]]; then
    echo "error: on branch '$current_branch', expected '$expected_branch' (set SYNAPSE_BRANCH)" >&2
    exit 1
fi
if ! git diff --quiet HEAD -- "${data_files[@]}"; then
    echo "error: uncommitted changes to ${data_files[*]}; commit or stash them first" >&2
    exit 1
fi

python3 update.py
python3 -m unittest discover -s tests -q

if git diff --quiet HEAD -- "${data_files[@]}"; then
    echo "No changes to commit."
    exit 0
fi

new_titles="$(git diff HEAD -U0 -- episodes.json | sed -n 's/^+    "title": "\(.*\)",$/- \1/p')"
git commit --quiet -m "Add new Project Synapse episodes (weekly update)" -m "$new_titles" -- "${data_files[@]}"
git log --oneline -1
git push origin HEAD
