#!/bin/bash
# Produce OpenCode's offline sources. Requires a working `bun`.
#
# Rule: no prebuilt binaries. bun install is JS-only (--ignore-scripts).
# Do not use --os=linux --cpu=* to pull npm optional native packages
# (@opentui/core-linux-*, @ff-labs/fff-bin-*). Those .so files are
# prebuilts. %build compiles libopentui.so (Zig) and libfff_c.so
# (Rust) from source and stages the JS wrappers bun --compile needs.
set -euo pipefail

VERSION="${1:-1.18.22}"
HERE=$(cd "$(dirname "$0")" && pwd)
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

echo "==> bun install --ignore-scripts (JS only, host platform)"
(
	cd "$SRC"
	export HOME="$WORKDIR/home"
	mkdir -p "$HOME"
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

	# JS wrappers only — never pack ELF/PE/Mach-O natives or npm tool binaries.
	find . -type f \( \
		-name '*.so' -o -name '*.node' -o -name '*.dll' -o -name '*.dylib' -o \
		-name '*.exe' -o -name '*.a' -o -name '*.bare' -o \
		-name 'esbuild' -o -name 'turbo' -o -name 'oxlint' \
		\) -delete
	find . -type f \( -name 'sst' -o -name 'rollup' -o -name 'lightningcss' \) -delete
	# Catch natives that do not use a conventional extension (xsel, tsgo, …).
	find . -type f ! -name '*.js' ! -name '*.ts' ! -name '*.json' ! -name '*.md' \
		! -name '*.map' ! -name '*.wasm' -print0 |
		xargs -0 -r file -N |
		awk -F': ' '$2 ~ /^(ELF|PE32|Mach-O|MS-DOS)/ { print $1 }' |
		xargs -r rm -f
	# Drop leftover optional platform packages entirely; %build recreates
	# the host-arch wrappers next to the from-source .so.
	find . -type d \( \
		-name 'core-linux-*' -o \
		-name 'core-darwin-*' -o \
		-name 'core-win32-*' -o \
		-name 'fff-bin-*' \
		\) -prune -exec rm -rf {} +

	tar -cJf "$HERE/opencode-${VERSION}-node_modules.tar.xz" \
		node_modules \
		packages/*/node_modules \
		packages/*/*/node_modules \
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
echo "  $HERE/opentui-zig-0.4.5.tar.xz"
echo "  $HERE/fff-0.9.4-with-vendor.tar.xz"
