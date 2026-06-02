{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.homeshare;
  settingsFormat = pkgs.formats.json {};
  configurationFile = settingsFormat.generate "homeshare_config.json" cfg.settings;
in {
  options.services.homeshare = {
    enable = lib.mkEnableOption "Homeshare file sharing service";

    user = lib.mkOption {
      description = "User account under which Homeshare runs.";
      type = lib.types.str;
      default = "homeshare";
    };

    group = lib.mkOption {
      description = "Group under which Homeshare runs.";
      type = lib.types.str;
      default = "homeshare";
    };

    bindPath = lib.mkOption {
      description = "Path of the Unix domain socket to bind to.";
      type = lib.types.str;
      default = "/run/homeshare/homeshare.sock";
    };

    socketUser = lib.mkOption {
      description = "User that owns the Unix domain socket (e.g. a reverse proxy user).";
      type = lib.types.nullOr lib.types.str;
      default = null;
    };

    settings = lib.mkOption {
      type = lib.types.submodule {
        freeformType = lib.types.attrsOf settingsFormat.type;

        options = {
          SECRET_KEY_FILE = lib.mkOption {
            description = ''
              Path to a file containing the Flask secret key.

              This key is used to cryptographically sign session cookies.
              It must be kept secret and must not be stored in the Nix store.

              To generate a secure key:

              ```bash
              python3 -c "import secrets; print(secrets.token_hex())"
              ```
            '';
            type = lib.types.path;
            example = "/run/secrets/homeshare_secret_key";
          };

          UPLOAD_DIR = lib.mkOption {
            description = "Directory where uploaded files are stored.";
            type = lib.types.path;
            default = "/var/lib/homeshare/uploads";
          };

          DATABASE_URL = lib.mkOption {
            description = "SQLAlchemy database URL.";
            type = lib.types.str;
            default = "sqlite:////var/lib/homeshare/homeshare.db";
          };

          OIDC_CLIENT_ID = lib.mkOption {
            description = "OIDC client ID registered with the identity provider.";
            type = lib.types.str;
          };

          OIDC_CLIENT_SECRET_FILE = lib.mkOption {
            description = ''
              Path to a file containing the OIDC client secret.
              Must not be stored in the Nix store.
            '';
            type = lib.types.path;
            example = "/run/secrets/homeshare_oidc_client_secret";
          };

          OIDC_DISCOVERY_URL = lib.mkOption {
            description = "OIDC discovery document URL for the identity provider.";
            example = "https://sso.example.com/.well-known/openid-configuration";
            type = lib.types.str;
          };

          PUBLIC_URL = lib.mkOption {
            description = "Public HTTPS base URL of the homeshare instance.";
            example = "https://homeshare.example.com";
            type = lib.types.str;
          };

          MAX_CONTENT_LENGTH = lib.mkOption {
            description = "Maximum upload size in bytes.";
            type = lib.types.int;
            default = 1024 * 1024 * 1024; # 1 GiB
          };

          SESSION_COOKIE_SAMESITE = lib.mkOption {
            description = ''
              SameSite attribute for session cookies.

              - "Strict": cookie is only sent on same-site requests.
              - "Lax": cookie is also sent on top-level navigations from external sites.

              Use "Lax" if homeshare and the IdP are on different registrable
              domains.
            '';
            type = lib.types.enum ["Strict" "Lax"];
            default = "Strict";
          };

          ROLES_PATH = lib.mkOption {
            description = ''
              JSON path within the OIDC access token or userinfo claims to
              a list of role strings.

              Example for Keycloak:
                ["resource_access" "homeshare" "roles"]
              Example for Kanidm:
                ["homeshare_roles"]
            '';
            type = lib.types.listOf lib.types.str;
          };

          USER_ROLE = lib.mkOption {
            description = ''
              Role name that grants standard user access.
              Users must have this role (or the admin role) in their OIDC
              token to access the application.
            '';
            type = lib.types.str;
            default = "homeshare_users";
          };

          ADMIN_ROLE = lib.mkOption {
            description = "Role name that grants admin access.";
            type = lib.types.str;
            default = "homeshare_admins";
          };

          LOG_LEVEL = lib.mkOption {
            description = "Logging level for the homeshare application.";
            type = lib.types.enum ["DEBUG" "INFO" "WARNING" "ERROR" "CRITICAL"];
            default = "WARNING";
          };
        };
      };
    };
  };

  config = lib.mkIf cfg.enable {
    users.users.${cfg.user} = lib.mkIf (cfg.user == "homeshare") {
      isSystemUser = true;
      group = cfg.group;
      description = "Homeshare service user";
    };

    users.groups.${cfg.group} = lib.mkIf (cfg.group == "homeshare") {};

    systemd.tmpfiles.settings."10-homeshare"."${cfg.settings.UPLOAD_DIR}".d = {
      group = cfg.group;
      mode = "0750";
      user = cfg.user;
    };

    systemd.sockets.homeshare = {
      description = "Homeshare file sharing service socket";
      wantedBy = ["sockets.target"];
      listenStreams = [cfg.bindPath];
      socketConfig = {
        SocketMode = "0660";
        SocketUser = cfg.socketUser;
        RemoveOnStop = true;
        FlushPending = true;
      };
    };

    systemd.services.homeshare = {
      description = "Homeshare file sharing service";
      wantedBy = ["multi-user.target"];
      bindsTo = ["homeshare.socket"];
      after = ["homeshare.socket"];

      environment = {
        HOMESHARE_CONFIG_FILE = "${configurationFile}";
        FLASK_APP = "homeshare.wsgi:application";
        # Use the NixOS system CA bundle so that self-signed or private CA
        # certificates trusted via security.pki.certificateFiles are also
        # trusted by Python's ssl module and the requests library.
        SSL_CERT_FILE = "/etc/ssl/certs/ca-bundle.crt";
        REQUESTS_CA_BUNDLE = "/etc/ssl/certs/ca-bundle.crt";
      };

      serviceConfig = {
        ExecStartPre = let
          flask = lib.getExe' pkgs.homeshare-server "flask";
        in [
          "${flask} db upgrade --directory ${pkgs.homeshare-server}/share/homeshare/migrations"
          "${flask} cleanup"
        ];
        ExecStart = "${lib.getExe' pkgs.homeshare-server "gunicorn"} --bind unix:${cfg.bindPath} homeshare.wsgi:application";
        User = cfg.user;
        Group = cfg.group;
        Restart = "on-failure";
        RestartSec = 10;
        Type = "idle";
        KillSignal = "SIGINT";

        # State directory for uploads
        StateDirectory = "homeshare";
        StateDirectoryMode = "0700";

        # Hardening
        DevicePolicy = "closed";
        CapabilityBoundingSet = "";
        RestrictAddressFamilies = ["AF_UNIX" "AF_INET" "AF_INET6"];
        DeviceAllow = "";
        NoNewPrivileges = true;
        PrivateDevices = true;
        PrivateMounts = true;
        PrivateTmp = true;
        PrivateUsers = true;
        ProtectClock = true;
        ProtectControlGroups = true;
        ProtectHome = true;
        ProtectKernelLogs = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        ProtectSystem = "strict";
        BindPaths = [cfg.settings.UPLOAD_DIR];
        MemoryDenyWriteExecute = true;
        LockPersonality = true;
        RemoveIPC = true;
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        SystemCallArchitectures = "native";
        SystemCallFilter = [
          "@system-service"
          "~@privileged"
          "~@resources"
        ];
        ProtectProc = "invisible";
        ProtectHostname = true;
        ProcSubset = "pid";
        UMask = "0077";
      };
    };
  };

  meta.maintainers = pkgs.homeshare-server.meta.maintainers;
}
