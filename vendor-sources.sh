#!/bin/bash
# Produce OpenCode's offline sources. Requires a working `bun` (the one
# we just packaged, or any bun that can read bun.lock).
#
# Native .node binaries are deleted before packing — %build rebuilds them.
set -euo pipefail

VERSION="${1:-1.18.22}"
HERE=$(cd "$(dirname "$0")" && pwd)
# /tmp is a small tmpfs on this machine; bun extract + node_modules
# will not fit. Keep the work tree on the same disk as the sources.
WORKDIR=$(mktemp -d -p "${TMPDIR:-$HERE}")
export TMPDIR="$WORKDIR"
trap 'rm -rf "$WORKDIR"' EXIT

TGZ="$HERE/opencode-${VERSION}.tar.gz"
if [ ! -f "$TGZ" ]; then
	curl -fL -o "$TGZ" \
		"https://github.com/anomalyco/opencode/archive/v${VERSION}/opencode-${VERSION}.tar.gz"
fi

tar -xf "$TGZ" -C "$WORKDIR"
SRC="$WORKDIR/opencode-${VERSION}"

echo "==> bun install --ignore-scripts"
(
	cd "$SRC"
	export HOME="$WORKDIR/home"
	mkdir -p "$HOME"
	# CLI + the workspace packages it imports. Skip desktop/electron/
	# storybook/web so the tarball stays a few hundred MB, not gigs.
	bun install --frozen-lockfile --ignore-scripts --no-progress \
		--filter opencode \
		--filter '@opencode-ai/core' \
		--filter '@opencode-ai/script' \
		--filter '@opencode-ai/sdk' \
		--filter '@opencode-ai/plugin' \
		--filter '@opencode-ai/protocol' \
		--filter '@opencode-ai/schema' \
		--filter '@opencode-ai/server' \
		--filter '@opencode-ai/tui' \
		--filter '@opencode-ai/llm' \
		--filter '@opencode-ai/codemode' \
		--filter '@opencode-ai/http-recorder'
	find . -type f \( -name '*.node' -o -name '*.exe' \) -delete
	# Isolated linker may put per-workspace node_modules under packages/.
	tar -cJf "$HERE/opencode-${VERSION}-node_modules.tar.xz" \
		node_modules \
		packages/*/node_modules \
		2>/dev/null || \
	tar -cJf "$HERE/opencode-${VERSION}-node_modules.tar.xz" node_modules
)

echo "==> models.dev API snapshot"
curl -fL -o "$HERE/models-dev-api.json" "https://models.dev/api.json"

echo
echo "Store these with abb store:"
echo "  $TGZ"
echo "  $HERE/opencode-${VERSION}-node_modules.tar.xz"
echo "  $HERE/models-dev-api.json"
