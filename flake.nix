{
  description = "A simple file sharing service for home servers";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    treefmt.url = "github:numtide/treefmt-nix";
    treefmt.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = {
    self,
    nixpkgs,
    treefmt,
  }: let
    overlay = final: prev: {
      homeshare-server = prev.callPackage ./server/package.nix {
        src = nixpkgs.lib.fileset.toSource {
          root = ./server;
          fileset = nixpkgs.lib.fileset.unions [
            ./server/homeshare
            ./server/migrations
            ./server/tests
            ./server/pyproject.toml
          ];
        };
      };

      homeshare-cli = prev.callPackage ./cli/package.nix {
        src = nixpkgs.lib.fileset.toSource {
          root = ./cli;
          fileset = nixpkgs.lib.fileset.unions [
            ./cli/homeshare_cli
            ./cli/tests
            ./cli/pyproject.toml
          ];
        };
      };
    };

    forEachSystem = nixpkgs.lib.genAttrs [
      "aarch64-darwin"
      "aarch64-linux"
      "x86_64-linux"
    ];
    importPkgs = system:
      import nixpkgs {
        inherit system;
        overlays = [overlay];
      };

    treefmtSettings = {
      projectRootFile = "flake.nix";
      programs = {
        alejandra.enable = true;
        prettier.enable = true;
        ruff-format.enable = true;
        taplo.enable = true;
      };
    };
  in {
    overlays = {
      default = overlay;
      homeshare = overlay;
    };

    nixosModules = {
      default = import ./nixos/module.nix;
      homeshare = import ./nixos/module.nix;
    };

    apps = forEachSystem (
      system: let
        pkgs = importPkgs system;
      in {
        default = {
          type = "app";
          program = nixpkgs.lib.getExe pkgs.homeshare-cli;
          inherit (pkgs.homeshare-cli) meta;
        };
      }
    );

    packages = forEachSystem (
      system: let
        pkgs = importPkgs system;
      in {
        inherit (pkgs) homeshare-cli homeshare-server;
      }
    );

    formatter = forEachSystem (
      system: (treefmt.lib.evalModule (importPkgs system) treefmtSettings).config.build.wrapper
    );

    devShells = forEachSystem (
      system: let
        pkgs = importPkgs system;
        pythonEnv = pkgs.python3.withPackages (ps:
          with ps; [
            authlib
            click
            flask
            flask-migrate
            flask-session
            flask-sqlalchemy
            flask-wtf
            keyring
            platformdirs
            pytest
            pytest-cov
            pytest-flask
            requests
            responses
            rich
            ruff
            setuptools
            systemd-python
            tomli-w
            ty
          ]);
      in {
        default = pkgs.mkShell {
          packages = [
            pythonEnv
            pkgs.pkg-config
            pkgs.systemd
          ];
        };
      }
    );

    checks = forEachSystem (
      system: let
        pkgs = importPkgs system;
      in {
        inherit (pkgs) homeshare-cli homeshare-server;

        nixos-basic = pkgs.callPackage ./nixos/tests/basic.nix {inherit self;};

        formatting = ((treefmt.lib.evalModule pkgs (nixpkgs.lib.recursiveUpdate treefmtSettings
          {
            programs.ruff-check.enable = true;
          }))
          .config
          .build
          .check)
        self;
      }
    );
  };
}
