# Homeshare

A simple file sharing service for home servers. Upload a file, get a link.

Homeshare is designed for sending large files to family and friends without the use of a cloud service.

This is my solution for [XKCD 949](https://xkcd.com/949/).

## What it is

- Authenticated users upload files and receive shareable download links.
  - Download links have an optional expiry date.
- Users sign in through an external OIDC provider (Kanidm, Keycloak, etc.)
  - Homeshare doesn't manage passwords or user accounts itself.
- Anyone with the link can download files, no account required.

## What it isn't

- Homeshare is designed for the scale of home use.
  - Files are stored on the local filesystem, not S3 or other object storage.
  - URLs are stored in an SQLite database, unlike S3's stateless signed URLs.
- Homeshare is not designed for simple home setups.
  - HTTPS is required at all times.
  - SSO via OIDC is required.
- No media streaming, transcoding, or thumbnails. Files download as-is.

## Security

Please report vulnerabilities to my git committer email.

## Technology

- Language: [Python](https://www.python.org)
- Web framework: [Flask](https://flask.palletsprojects.com)
- WSGI server: [Gunicorn](https://gunicorn.org)
- Database ORM: [Flask-SQLAlchemy](https://flask-sqlalchemy.readthedocs.io)
- Database migrations: [Flask-Migrate](https://flask-migrate.readthedocs.io)
- OIDC / OAuth2 client: [Authlib](https://authlib.org)
- CSRF protection: [Flask-WTF](https://flask-wtf.readthedocs.io)
- CLI: [Click](https://click.palletsprojects.com)

## Configuration

This is designed to work with [NixOS], but should work on any Linux OS with systemd.

You need to bring a reverse proxy for TLS, I suggest [nginx].

The server reads its configuration from a JSON file. The path to the file is
passed via the `HOMESHARE_CONFIG_FILE` environment variable (set automatically
by the NixOS module).

### Config file reference

**Required keys:**

- `SECRET_KEY_FILE` - Path to a file containing the Flask secret key (signs session
  cookies). Must not be in the Nix store. Generate with:
  `python3 -c "import secrets; print(secrets.token_hex())"`
- `UPLOAD_DIR` - Directory where uploaded files are stored.
- `OIDC_CLIENT_ID` - OIDC client ID registered with the identity provider.
- `OIDC_CLIENT_SECRET_FILE` - Path to a file containing the OIDC client secret.
  Must not be in the Nix store.
- `OIDC_DISCOVERY_URL` - OIDC discovery document URL. Must be HTTPS.
- `PUBLIC_URL` - Public HTTPS base URL of the homeshare instance. Must be HTTPS.
- `ROLES_PATH` - JSON path within the OIDC token or userinfo claims to a list of
  role strings. Provider-specific; see sections below.

**Optional keys:**

- `DATABASE_URL` - SQLAlchemy database URL.
  Default: `"sqlite:////var/lib/homeshare/homeshare.db"`
- `USER_ROLE` - Role name that grants standard user access.
  Default: `"homeshare_users"`
- `ADMIN_ROLE` - Role name that grants admin access.
  Default: `"homeshare_admins"`
- `MAX_CONTENT_LENGTH` - Maximum upload size in bytes.
  Default: `1073741824` (1 GiB)
- `SESSION_COOKIE_SAMESITE` - SameSite attribute for session cookies. Use `"Lax"`
  if homeshare and your IdP are on different registrable domains.
  Default: `"Strict"`

### Kanidm configuration

Create the OAuth2 client:

```bash
kanidm system oauth2 create homeshare "homeshare" https://homeshare.example.com
kanidm system oauth2 update-scope-map homeshare homeshare_users openid email profile groups
kanidm system oauth2 get homeshare
kanidm system oauth2 show-basic-secret homeshare
<SECRET>
```

Create permission groups:

```bash
kanidm group create 'homeshare_users'
kanidm group create 'homeshare_admins'
```

Setup the claim map:

```bash
kanidm system oauth2 update-claim-map-join 'homeshare' 'homeshare_roles' array
kanidm system oauth2 update-claim-map 'homeshare' 'homeshare_roles' 'homeshare_users' 'homeshare_users'
kanidm system oauth2 update-claim-map 'homeshare' 'homeshare_roles' 'homeshare_admins' 'homeshare_admins'
```

Add users to groups:

```bash
kanidm group add-members 'homeshare_users' 'myusername'
```

Set `ROLES_PATH` to `["homeshare_roles"]` in the config.

### Keycloak configuration

- Create and enable an OpenID Connect client in your realm
  - Root URL: `https://homeshare.example.com`
  - Home URL: `https://homeshare.example.com`
  - Valid redirect URIs: `https://homeshare.example.com/auth/callback`
  - Client authentication: `On`
  - Authorization: `Off`
  - Authentication flow: `Standard flow` (all others disabled)
- Create roles for the newly created client
  - `homeshare_users` grants standard user access
  - `homeshare_admins` grants admin access
- Create a dedicated audience mapper for the newly created client
  - Navigate to **Clients** -> `<client_id>` -> **Client scopes**
    -> `<client_id>-dedicated` -> **Configure a new mapper** -> **Audience**
  - Name: `aud-mapper-<client_id>`
  - Included Client Audience: `<client_id>`
  - Add to ID token: `On`
  - Add to access token: `On`
  - Add to lightweight access token: `Off`
  - Add to token introspection: `On`

Set `OIDC_DISCOVERY_URL` to `https://sso.example.com/realms/<realm>/.well-known/openid-configuration`
and `ROLES_PATH` to `["resource_access", "<client_id>", "roles"]` in the config.

### NixOS configuration

Reference `nixos/module.nix` for a complete list of options,
below is an example configuration.

```nix
{
  homeshare,
  config,
  ...
}: let
  domain = "homeshare.example.com";
in {
  # import the module, this adds the "services.homeshare" options
  imports = [homeshare.nixosModules.default];

  # add the overlay, this puts "homeshare-server" into "pkgs"
  nixpkgs.overlays = [homeshare.overlays.default];

  # use sops-nix to manage secrets declaratively
  # https://github.com/Mic92/sops-nix
  sops.secrets.homeshare_secret_key.mode = "0400";
  sops.secrets.homeshare_oidc_secret.mode = "0400";

  # reference module for descriptions of configuration options
  services.homeshare = {
    enable = true;
    # give nginx access to the homeshare socket
    socketUser = config.services.nginx.user;
    settings = {
      SECRET_KEY_FILE = config.sops.secrets.homeshare_secret_key.path;
      UPLOAD_DIR = "/var/lib/homeshare/uploads";
      OIDC_CLIENT_ID = "homeshare";
      OIDC_CLIENT_SECRET_FILE = config.sops.secrets.homeshare_oidc_secret.path;
      PUBLIC_URL = "https://${domain}";

      # provider specific:
      # - kanidm: "https://sso.example.com/oauth2/openid/homeshare/.well-known/openid-configuration"
      # - keycloak: "https://sso.example.com/realms/<realm>/.well-known/openid-configuration"
      OIDC_DISCOVERY_URL = "";

      # provider specific:
      # - kanidm: ["homeshare_roles"]
      # - keycloak: ["resource_access" "homeshare" "roles"]
      ROLES_PATH = [];
    };
  };

  # use nginx as a reverse proxy to provide a TLS (https) interface
  networking.firewall.allowedTCPPorts = [443];
  services.nginx = {
    enable = true;
    virtualHosts."${domain}" = {
      onlySSL = true;
      locations."/".proxyPass = "http://unix:${config.services.homeshare.bindPath}";
    };
  };
}
```

## CLI

The `homeshare-cli` package provides a command-line client for uploading files.

The CLI stores its configuration at `~/.config/homeshare/config.toml`.
Tokens are stored in the system keyring by default.

### Login

```bash
homeshare login https://homeshare.example.com myserver
```

You will be prompted to paste an API token. Tokens can be created from the
web UI under **Account** -> **API tokens**.

#### Headless / keyring-free use

On headless systems without a keyring, add `token_file` to the server entry in
`~/.config/homeshare/config.toml` and skip `homeshare login`:

```toml
[servers.myserver]
url = "https://homeshare.example.com"
token_file = "/run/secrets/homeshare_token"
```

The token file must have permissions `0600`. `homeshare logout` does not work
with `token_file` servers; remove the entry from the config file manually.

### Upload

```bash
homeshare upload myfile.tar.gz # default link never expires
homeshare upload myfile.tar.gz --expiry "7 days"
```

### List shares

```bash
homeshare list
```

### Delete a share or link

```bash
homeshare delete $SHARE_ID
```

### Logout

```bash
homeshare logout
```

## Development

### Running checks

Each package has its own directory with its own `pyproject.toml` and `uv` environment.

Run these commands:

- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run ty check .`

In these directories:

- `server`
- `lib`
- `cli`

Running `nix flake check` will build all packages and run the full test suite including end-to-end NixOS tests.

### Interactive VM for manual end to end testing

The NixOS test spins up a fully provisioned VM with kanidm (OIDC) and homeshare
already configured, which is the easiest way to test the full login flow without
setting up your own SSO provider.

From your host, add this line to `/etc/hosts`:

```
127.0.0.1 homeshare.home.arpa kanidm.home.arpa
```

Start the interactive VM with port forwarding:

```bash
QEMU_NET_OPTS="hostfwd=tcp::10443-:10443,hostfwd=tcp::20443-:20443" nix run .#checks.x86_64-linux.nixos-basic.driverInteractive
```

This drops you into a Python REPL. Boot the machine:

```python
start_all()
```

To get a shell on the VM run this command in the REPL,
or log in as `root` with no password at the VM login prompt.

```python
machine.shell_interact()
```

To get a usable password for the kanidm `testuser`, run inside the VM:

```bash
kanidmd recover-account testuser 2>&1 | grep -oP '[A-Za-z0-9]{48}'
```

Then visit `https://homeshare.home.arpa:10443`. Kanidm is at
`https://kanidm.home.arpa:20443`.

## AI disclosure

This project was built with the assistance of AI coding agents.
It is not vibe-coded, all generated code was reviewed by a human before being accepted.

However, this was a learning project for me, this is my second time working on a web-app (the first being [OIDC Pages](https://github.com/newAM/oidc_pages)), and the first time working on a web-app with a database.

[NixOS]: https://nixos.org
[nginx]: https://nginx.org
