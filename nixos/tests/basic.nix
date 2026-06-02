{
  self,
  pkgs,
}: let
  homeshareDomain = "homeshare.home.arpa";
  kanidmDomain = "kanidm.home.arpa";
  nginxPort = 10443;
  kanidmPort = 20443;
  kanidmFrontendUrl = "https://${kanidmDomain}:${toString kanidmPort}";
  homeshareUrl = "https://${homeshareDomain}:${toString nginxPort}";

  SECRET_KEY_FILE = "/run/homeshare_secret_key";
  oidcClientId = "homeshare";
  oidcClientSecretFile = pkgs.writeText "homeshare_oidc_client_secret" "test-oidc-client-secret";
  oidcDiscoveryUrl = "${kanidmFrontendUrl}/oauth2/openid/${oidcClientId}/.well-known/openid-configuration";

  kanidmUsername = "testuser";
in
  pkgs.testers.nixosTest {
    name = "homeshare-basic";

    nodes.machine = {config, ...}: {
      imports = [self.nixosModules.default];
      nixpkgs.overlays = [self.overlays.default];

      networking.hosts."127.0.0.1" = [homeshareDomain kanidmDomain];
      networking.firewall.allowedTCPPorts = [nginxPort kanidmPort];

      # kanidm identity provider
      services.kanidm = {
        package = pkgs.kanidmWithSecretProvisioning_1_10;
        server = {
          enable = true;
          settings = {
            version = "2";
            bindaddress = "0.0.0.0:${toString kanidmPort}";
            domain = kanidmDomain;
            origin = kanidmFrontendUrl;
            tls_chain = ./kanidm.home.arpa.cert.pem;
            tls_key = ./kanidm.home.arpa.key.pem;
          };
        };
        client = {
          enable = true;
          settings = {
            uri = kanidmFrontendUrl;
            verify_ca = true;
            verify_hostnames = true;
          };
        };
        provision = {
          enable = true;
          systems.oauth2.${oidcClientId} = {
            displayName = "Homeshare";
            public = false;
            enableLegacyCrypto = false;
            preferShortUsername = true;
            basicSecretFile = oidcClientSecretFile;
            originUrl = "${homeshareUrl}/auth/callback";
            originLanding = homeshareUrl;
            scopeMaps."homeshare_users" = ["openid" "email" "profile"];
            removeOrphanedClaimMaps = true;
            claimMaps."homeshare_roles".valuesByGroup."homeshare_users" = ["homeshare_users"];
          };
          persons.${kanidmUsername} = {
            displayName = "Test User";
            mailAddresses = ["testuser@example.com"];
          };
          groups."homeshare_users".members = [kanidmUsername];
        };
      };

      # homeshare application
      services.homeshare = {
        enable = true;
        socketUser = config.services.nginx.user;
        settings = {
          inherit SECRET_KEY_FILE;
          OIDC_CLIENT_SECRET_FILE = toString oidcClientSecretFile;
          OIDC_CLIENT_ID = oidcClientId;
          OIDC_DISCOVERY_URL = oidcDiscoveryUrl;
          PUBLIC_URL = homeshareUrl;
          # .arpa is on the public suffix list, so the browser treats
          # homeshare.home.arpa and kanidm.home.arpa as cross-site.
          # Use Lax so the IdP callback redirect carries the session cookie.
          SESSION_COOKIE_SAMESITE = "Lax";
          ROLES_PATH = ["homeshare_roles"];
        };
      };

      services.nginx = {
        enable = true;
        defaultSSLListenPort = nginxPort;
        virtualHosts.${homeshareDomain} = {
          onlySSL = true;
          sslCertificate = ./homeshare.home.arpa.cert.pem;
          sslCertificateKey = ./homeshare.home.arpa.key.pem;
          extraConfig = "client_max_body_size ${toString config.services.homeshare.settings.MAX_CONTENT_LENGTH};";
          locations."/".proxyPass = "http://unix:${config.services.homeshare.bindPath}";
        };
      };

      security.pki.certificateFiles = [
        ./homeshare.home.arpa.cert.pem
        ./kanidm.home.arpa.cert.pem
      ];

      # Write the Flask secret key before homeshare starts
      systemd.services.homeshare-test-secret = {
        description = "Write test secret key for homeshare";
        wantedBy = ["homeshare.service"];
        before = ["homeshare.service"];
        script = ''
          echo test-secret-key-do-not-use-in-production > ${SECRET_KEY_FILE}
          chmod 600 ${SECRET_KEY_FILE}
          chown homeshare:homeshare ${SECRET_KEY_FILE}
        '';
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
      };

      environment.systemPackages = with pkgs; [
        htmlq
        (symlinkJoin {
          name = "homeshare-cli-wrapped";
          paths = [homeshare-cli];
          nativeBuildInputs = [makeWrapper];
          postBuild = ''
            wrapProgram $out/bin/homeshare \
              --prefix PYTHONPATH : ${python3Packages.keyrings-alt}/${python3.sitePackages}
          '';
        })
      ];
    };

    testScript = ''
      import json
      import re

      def get_csrf(path: str) -> str:
        machine.succeed(
            "curl -sSf -b homeshare_cookies.txt -o csrf.html ${homeshareUrl}" + path,
            "htmlq 'input[name=csrf_token]' --attribute value --filename csrf.html --output csrf.txt",
        )
        return machine.succeed("head -1 csrf.txt").rstrip()

      machine.wait_for_unit("kanidm.service")
      machine.wait_for_open_port(${toString kanidmPort})
      machine.wait_until_succeeds("curl -sSf ${kanidmFrontendUrl}")

      # recover a password for the test user
      pw = machine.succeed(
        "kanidmd recover-account ${kanidmUsername} 2>&1 | grep -oP '[A-Za-z0-9]{48}'"
      ).strip()

      machine.wait_for_unit("homeshare.socket")
      machine.wait_for_unit("homeshare.service")
      machine.wait_for_unit("nginx.service")

      with subtest("Health check"):
        response = machine.succeed("curl -sf ${homeshareUrl}/api/health")
        data = json.loads(response)
        assert data == {"status": "ok"}, f"unexpected response: {data}"

      with subtest("Unauthenticated upload"):
        machine.succeed("echo 'hello world' > /tmp/upload.txt")
        status = machine.succeed(
          "curl -s -o /dev/null -w '%{http_code}' -F 'file=@/tmp/upload.txt' ${homeshareUrl}/upload"
        ).strip()
        # 400 because of the lack of CSRF token
        # CSRF token can only be obtained from authenticated index.html
        assert status == "400", f"expected 400, got: {status}"

      with subtest("Login"):
        # follow /login -> kanidm authorize redirect; capture the SSO login URL
        sso_login_url: str = machine.succeed(
          "curl -sSf -c homeshare_cookies.txt -w %{redirect_url} -o /dev/null ${homeshareUrl}/login"
        ).rstrip()
        print(f"{sso_login_url=}")

        # fetch the username form page
        machine.succeed(
          f"curl -sSf -c sso_cookies.txt -o login_page.html '{sso_login_url}'",
          "htmlq '#login' --attribute action --filename login_page.html --output username_form_action.txt",
        )
        username_post_url: str = "${kanidmFrontendUrl}" + machine.succeed("cat username_form_action.txt").rstrip()
        print(f"{username_post_url=}")

        # post username, get the password form page
        machine.succeed(
          f"curl -sSf -b sso_cookies.txt -c sso_cookies.txt -o password_page.html"
          f" -d 'username=${kanidmUsername}' -d 'password=' -d 'totp='"
          f" '{username_post_url}'",
          "htmlq '#login' --attribute action --filename password_page.html --output password_form_action.txt",
        )
        password_post_url: str = "${kanidmFrontendUrl}" + machine.succeed("cat password_form_action.txt").rstrip()
        print(f"{password_post_url=}")

        # post password, get resume session redirect
        resume_url: str = machine.succeed(
          f"curl -sSf -b sso_cookies.txt -c sso_cookies.txt -w %{{redirect_url}} -o /dev/null"
          f" -d 'password={pw}' '{password_post_url}'"
        ).rstrip()
        print(f"{resume_url=}")
        assert resume_url.startswith("https://"), f"invalid resume URL: {resume_url!r}"

        # follow resume url, get consent page
        machine.succeed(
          f"curl -sSf -b sso_cookies.txt -c sso_cookies.txt -o consent_page.html '{resume_url}'",
          "htmlq '#login' --attribute action --filename consent_page.html --output consent_form_action.txt",
          "htmlq '#consent_token' --attribute value --filename consent_page.html --output consent_token.txt",
        )
        consent_post_url: str = "${kanidmFrontendUrl}" + machine.succeed("cat consent_form_action.txt").rstrip()
        consent_token: str = machine.succeed("cat consent_token.txt").rstrip()
        print(f"{consent_post_url=}")
        print(f"{consent_token=}")

        # post consent, get callback redirect back to homeshare
        callback_url: str = machine.succeed(
          f"curl -sSf -b sso_cookies.txt -c sso_cookies.txt -w %{{redirect_url}} -o /dev/null"
          f" -d 'consent_token={consent_token}' '{consent_post_url}'"
        ).rstrip()
        print(f"{callback_url=}")

        # follow the callback - establishes the homeshare session
        machine.succeed(
          f"curl -L -sSf -b homeshare_cookies.txt -c homeshare_cookies.txt -o /dev/null '{callback_url}'"
        )

      with subtest("Authenticated upload"):
        csrf_token: str = get_csrf("/")

        # upload a file via the web form - redirects to share detail page
        redirect_url: str = machine.succeed(
          f"curl -s -b homeshare_cookies.txt -o /dev/null -w '%{{redirect_url}}'"
          f" -F 'csrf_token={csrf_token}' -F 'file=@/tmp/upload.txt' ${homeshareUrl}/upload",
        ).rstrip()
        assert "/shares/" in redirect_url, f"expected redirect to /shares/, got: {redirect_url}"
        share_id = redirect_url.strip("/").split("/")[-1].split("?")[0]

        # fetch the share detail page to get the first link
        machine.succeed(
          f"curl -sSf -b homeshare_cookies.txt -o share_detail.html ${homeshareUrl}/shares/{share_id}",
        )
        link_href: str = machine.succeed(
          "htmlq 'a[href*=\"/links/\"]' --attribute href --filename share_detail.html | head -1",
        ).rstrip()
        link_id = link_href.strip("/").split("/")[1]

      with subtest("Download via web"):
        downloaded = machine.succeed(
          f"curl -sSf ${homeshareUrl}/links/{link_id}/download"
        )
        assert downloaded == "hello world\n", f"unexpected download content: {downloaded!r}"

      with subtest("Create second link via web"):
        csrf_link: str = get_csrf(f"/shares/{share_id}")

        machine.succeed(
          f"curl -s -b homeshare_cookies.txt -o /dev/null -w '%{{http_code}}'"
          f" -F 'csrf_token={csrf_link}' -F 'label=for Alice' -F 'expires_in=7 days'"
          f" ${homeshareUrl}/shares/{share_id}/links",
        )

        # re-fetch share detail, should now show two links
        detail3 = machine.succeed(
          f"curl -sSf -b homeshare_cookies.txt ${homeshareUrl}/shares/{share_id}"
        )
        assert "for Alice" in detail3, "second link label not found"

      with subtest("Delete share via web"):
        csrf2: str = get_csrf("/")

        delete_response = machine.succeed(
          f"curl -s -b homeshare_cookies.txt -o /dev/null -w '%{{http_code}}'"
          f" -F 'csrf_token={csrf2}' -F '_method=DELETE'"
          f" ${homeshareUrl}/shares/{share_id}",
        ).strip()
        assert delete_response == "302", f"expected 302, got: {delete_response}"

        status = machine.succeed(
          f"curl -s -o /dev/null -w '%{{http_code}}' ${homeshareUrl}/links/{link_id}/download",
        ).strip()
        assert status == "404", f"expected 404 after delete, got: {status}"

      with subtest("Create API token"):
        csrf3: str = get_csrf("/account")

        machine.succeed(
          f"curl -sSf -b homeshare_cookies.txt -o token_created.html"
          f" -F 'csrf_token={csrf3}' -F 'name=e2e-test-token' ${homeshareUrl}/account/tokens",
        )
        token_page = machine.succeed("cat token_created.html")
        assert "e2e-test-token" in token_page, "token name not in response"

        # extract the raw token (shown only once) from the <code> block
        api_token: str = machine.succeed(
          "htmlq 'code' --text --filename token_created.html",
        ).rstrip()
        assert api_token.startswith("hs_"), f"unexpected token format: {api_token!r}"

        # extract the token's database id for later deletion
        token_db_id: str = machine.succeed(
          "htmlq 'form[action*=\"/account/tokens/\"]' --attribute action --filename token_created.html | head -1",
        ).rstrip()
        token_db_id = token_db_id.strip("/").split("/")[-1]

      with subtest("Upload via API"):
        upload_resp = machine.succeed(
          f"curl -sSf -H 'Authorization: Bearer {api_token}'"
          f" -F 'file=@/tmp/upload.txt' ${homeshareUrl}/api/shares",
        )
        data = json.loads(upload_resp)
        assert "share_id" in data, f"no share_id: {data}"
        assert "link_id" in data, f"no link_id: {data}"
        api_share_id = data["share_id"]
        api_link_id = data["link_id"]

      with subtest("List via API"):
        list_resp = machine.succeed(
          f"curl -sSf -H 'Authorization: Bearer {api_token}' ${homeshareUrl}/api/shares",
        )
        shares = json.loads(list_resp)
        share = next(s for s in shares if s["share_id"] == api_share_id)
        assert any(lnk["link_id"] == api_link_id for lnk in share["links"]), "link not in list"

      with subtest("Download via API"):
        downloaded = machine.succeed(
          f"curl -sSf ${homeshareUrl}/api/links/{api_link_id}/download",
        )
        assert downloaded == "hello world\n", f"unexpected content: {downloaded!r}"

      with subtest("Create link via API"):
        link_resp = machine.succeed(
          f"curl -sSf -H 'Authorization: Bearer {api_token}'"
          f" -F 'label=API link' ${homeshareUrl}/api/shares/{api_share_id}/links",
        )
        link_data = json.loads(link_resp)
        assert link_data["label"] == "API link"
        second_link_id = link_data["link_id"]

        # second link should also work for download
        downloaded2 = machine.succeed(
          f"curl -sSf ${homeshareUrl}/api/links/{second_link_id}/download",
        )
        assert downloaded2 == "hello world\n"

      with subtest("Delete link via API"):
        del_resp = machine.succeed(
          f"curl -sSf -X DELETE -H 'Authorization: Bearer {api_token}'"
          f" ${homeshareUrl}/api/links/{second_link_id}",
        )
        assert json.loads(del_resp)["status"] == "deleted"

        # first link should still work
        downloaded3 = machine.succeed(
          f"curl -sSf ${homeshareUrl}/api/links/{api_link_id}/download",
        )
        assert downloaded3 == "hello world\n"

      with subtest("Delete share via API"):
        del_resp = machine.succeed(
          f"curl -sSf -X DELETE -H 'Authorization: Bearer {api_token}'"
          f" ${homeshareUrl}/api/shares/{api_share_id}",
        )
        assert json.loads(del_resp)["status"] == "deleted"

      with subtest("Delete API token"):
        csrf4: str = get_csrf("/account")

        machine.succeed(
          f"curl -sSf -b homeshare_cookies.txt -o /dev/null -w '%{{http_code}}'"
          f" -F 'csrf_token={csrf4}' -F '_method=DELETE' ${homeshareUrl}/account/tokens/{token_db_id}",
        )

      with subtest("Deleted token is rejected"):
        status = machine.succeed(
          f"curl -s -o /dev/null -w '%{{http_code}}' -H 'Authorization: Bearer {api_token}' ${homeshareUrl}/api/shares",
        ).rstrip()
        assert status == "401", f"expected 401 with deleted token, got: {status}"

      # --- CLI tests ---
      cli_env = "KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring XDG_CONFIG_HOME=/tmp/cli-config REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-bundle.crt SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt COLUMNS=999"

      # create a new API token for CLI use
      with subtest("Create API token for CLI"):
        csrf5: str = get_csrf("/account")

        machine.succeed(
          f"curl -sSf -b homeshare_cookies.txt -o cli_token_page.html"
          f" -F 'csrf_token={csrf5}' -F 'name=cli-test-token' ${homeshareUrl}/account/tokens",
        )
        cli_api_token: str = machine.succeed(
          "htmlq 'code' --text --filename cli_token_page.html",
        ).rstrip()
        assert cli_api_token.startswith("hs_"), f"unexpected token: {cli_api_token!r}"

      with subtest("CLI login"):
        machine.succeed(
          f"{cli_env} sh -c \"echo '{cli_api_token}' | homeshare login ${homeshareUrl} mysrv\"",
        )
        config_content = machine.succeed("cat /tmp/cli-config/homeshare/config.toml")
        assert "mysrv" in config_content, "server not in config"

      with subtest("CLI upload"):
        machine.succeed("echo 'cli upload test' > /tmp/cli_upload.txt")
        upload_out = machine.succeed(
          f"{cli_env} homeshare upload /tmp/cli_upload.txt",
        )
        assert "Uploaded cli_upload.txt" in upload_out, f"unexpected upload output: {upload_out}"
        url_match = re.search(r"Download URL:\s*(https://\S+)", upload_out)
        assert url_match, f"no download URL in output: {upload_out}"
        cli_download_url = url_match.group(1)

        del_match = re.search(r"homeshare delete (\S+)", upload_out)
        assert del_match, f"no delete hint in output: {upload_out}"
        cli_share_id = del_match.group(1)

        downloaded = machine.succeed(f"curl -sSf '{cli_download_url}'")
        assert downloaded == "cli upload test\n", f"unexpected content: {downloaded!r}"

      with subtest("CLI list"):
        list_out = machine.succeed(
          f"{cli_env} homeshare list",
        )
        assert "cli_upload.txt" in list_out, f"file not in list output: {list_out}"

      with subtest("CLI delete"):
        del_out = machine.succeed(
          f"{cli_env} homeshare delete {cli_share_id}",
        )
        assert f"Deleted share {cli_share_id}" in del_out, f"unexpected delete output: {del_out}"

      with subtest("CLI logout"):
        logout_out = machine.succeed(
          f"{cli_env} homeshare logout",
        )
        assert "Logged out" in logout_out, f"unexpected logout output: {logout_out}"

      with subtest("Logout"):
        csrf_logout: str = get_csrf("/")

        final_url: str = machine.succeed(
          f"curl -sSf -L -b homeshare_cookies.txt -c homeshare_cookies.txt -o /dev/null -w '%{{url_effective}}'"
          f" -F 'csrf_token={csrf_logout}' ${homeshareUrl}/logout",
        ).rstrip()
        assert "/logged-out" in final_url, f"expected /logged-out, got: {final_url}"

        # verify session is cleared, / should redirect to /login again
        redirect_after_logout: str = machine.succeed(
          "curl -sSf -b homeshare_cookies.txt -o /dev/null -w %{redirect_url} ${homeshareUrl}/"
        ).rstrip()
        assert "login" in redirect_after_logout, f"expected login redirect, got: {redirect_after_logout}"
    '';
  }
