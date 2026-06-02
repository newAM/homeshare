{
  installShellFiles,
  lib,
  python3Packages,
  stdenv,
  src,
}: let
  pyprojectToml = lib.importTOML (src + "/pyproject.toml");
in
  python3Packages.buildPythonApplication (finalAttrs: {
    pname = pyprojectToml.project.name;
    version = pyprojectToml.project.version;
    pyproject = true;

    inherit src;

    build-system = with python3Packages; [
      setuptools
    ];

    dependencies = with python3Packages; [
      click
      platformdirs
      requests
      rich
      tomli-w
      (python3Packages.callPackage ../lib/package.nix {})
    ];

    nativeCheckInputs = with python3Packages; [
      pytestCheckHook
      responses
      ty
    ];

    postCheck = ''
      ty check .
    '';

    nativeBuildInputs = [
      installShellFiles
    ];

    postInstall = lib.optionalString (stdenv.buildPlatform.canExecute stdenv.hostPlatform) ''
      installShellCompletion --cmd homeshare \
        --bash <(_HOMESHARE_COMPLETE=bash_source $out/bin/homeshare) \
        --fish <(_HOMESHARE_COMPLETE=fish_source $out/bin/homeshare) \
        --zsh <(_HOMESHARE_COMPLETE=zsh_source $out/bin/homeshare)
    '';

    meta = {
      description = pyprojectToml.project.description;
      homepage = pyprojectToml.project.urls.Repository;
      changelog = pyprojectToml.project.urls.Changelog;
      license = lib.licenses.agpl3Plus;
      maintainers = [lib.maintainers.newam];
      mainProgram = "homeshare";
    };
  })
