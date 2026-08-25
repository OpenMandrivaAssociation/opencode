# OpenCode CLI. Production artifact is a bun --compile standalone binary.
# node_modules is vendored (see vendor-sources.sh) because ABF has no
# network. Native addons are rebuilt from their C/C++ sources in %build
# so we never ship a prebuilt .node from npm.
#
# Depends on bun, which is the hard package — see ../bun/bun.spec.
#
# We ship the TUI/CLI only. The desktop app is a separate, much larger
# problem (Electron/Tauri + more npm native addons).
#
# First time, on a networked machine (after bun is installed):
#   ./vendor-sources.sh
#   abb store opencode-*.tar.gz opencode-*-node_modules.tar.xz models-dev-api.json

# bun --compile emits a standalone binary; there is no debugsource.
%define debug_package %{nil}

Name:		opencode
Version:	1.18.22
Release:	2
Summary:	Open-source AI coding agent
Group:		Development/Other
License:	MIT
URL:		https://opencode.ai/
Source0:	https://github.com/anomalyco/opencode/archive/v%{version}/opencode-%{version}.tar.gz
# bun install --frozen-lockfile --ignore-scripts, then strip prebuilt natives
Source1:	opencode-%{version}-node_modules.tar.xz
# Snapshot of https://models.dev/api.json — fetched at vendor time, not build time
Source2:	models-dev-api.json

BuildRequires:	bun
BuildRequires:	nodejs
BuildRequires:	clang
BuildRequires:	pkgconfig(libuv)
BuildRequires:	python
BuildRequires:	git
BuildRequires:	make

# Runtime: the compiled binary shells out to rg for codebase search.
# OpenMandriva's rg is the grep-based C++ ripgrep implementation
# (ripgrep-compatible CLI, including --json / --hidden / --glob).
Requires:	rg
Requires:	git

# fzf is used by some picker flows; available in cooker.
Requires:	fzf

%description
OpenCode is an open-source AI coding agent. It talks to any LLM provider
(or a local model) and edits a project from a terminal UI.

This package builds the official bun-compiled CLI from source. It does
not download the prebuilt GitHub-release binaries.

%prep
%autosetup -p1 -n opencode-%{version}

# Relax the bun version pin. We build with bun 1.4; upstream package.json
# still says bun@1.3.14. Nix does the same substitution.
sed -i \
	's/throw new Error(`This script requires bun@/console.warn(`Warning: This script requires bun@/' \
	packages/script/src/index.ts

tar -xf %{S:1}

# Anything that looks like a prebuilt native addon must be rebuilt.
# Leave the source trees; delete binaries that came from the registry.
find node_modules packages -type f \( \
	-name '*.node' -o \
	-name '*.exe' -o \
	-name 'esbuild' \
	\) -delete 2>/dev/null || :

install -m0644 %{S:2} models-dev-api.json

%build
export HOME=$(mktemp -d)
export OPENCODE_VERSION=%{version}
export OPENCODE_CHANNEL=prod
export OPENCODE_DISABLE_MODELS_FETCH=1
export OPENCODE_DISABLE_AUTOUPDATE=1
export MODELS_DEV_API_JSON="$PWD/models-dev-api.json"
# bun must not talk to the registry even if a script forgets --skip-install
export BUN_INSTALL_CACHE_DIR="$PWD/.bun-cache"
export npm_config_offline=true
export npm_config_ignore_scripts=true
export GIT_TERMINAL_PROMPT=0
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1

cd packages/opencode
# --skip-embed-web-ui: we do not vendor packages/app (desktop/web).
bun --bun ./script/build.ts --single --skip-install --skip-embed-web-ui
bun --bun ./script/schema.ts schema.json
cd -

%install
install -Dm0755 packages/opencode/dist/opencode-*/bin/opencode \
	%{buildroot}%{_bindir}/opencode
install -Dm0644 packages/opencode/schema.json \
	%{buildroot}%{_datadir}/opencode/schema.json

# Make sure the compiled binary can find rg without relying on the
# user's interactive PATH (rpmbuild %check runs with a minimal PATH).
# At runtime the user has /usr/bin on PATH already.

%check
export HOME=$(mktemp -d)
export OPENCODE_DISABLE_MODELS_FETCH=1
export OPENCODE_DISABLE_AUTOUPDATE=1
export PATH="%{buildroot}%{_bindir}:/usr/bin:$PATH"
opencode --version

%files
%license LICENSE
%doc README.md
%{_bindir}/opencode
%dir %{_datadir}/opencode
%{_datadir}/opencode/schema.json
