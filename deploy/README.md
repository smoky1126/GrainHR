# GrainHR on Google Cloud

HR opens `https://hr.<your-domain>` in a browser and signs in with a company Google account. The server has no public web port. Cloudflare Tunnel connects outward. The payroll files stay on the shared drive. The DAKA robot stays on a separate computer.

Do the code steps on the PC first. The clicks below happen once.

## 1. Rotate the rclone secret

The old Google client secret was pasted into a chat. In Google Cloud, open the GrainHR rclone client and create a new secret. Put the new secret in the rclone config on the robot computer and on the new server. Do not commit it.

## 2. Create the server

- Google Cloud, a region near the workplace, Ubuntu 24.04, machine type e2-medium.
- No HTTP or HTTPS firewall rule. SSH only, from your own address.
- SSH in and run `deploy/setup_vm.sh`.

## 3. Mount the shared drive

Copy the rclone config to the server. The remote name stays `grainhr`. Copy these unit files to `~/.config/systemd/user/` and enable them:

```
systemctl --user daemon-reload
systemctl --user enable --now grainhr-drive.service
```

Check that `/srv/grainhr/hr` shows the shared drive. `company.toml` on the server already has:

```
[server]
windows_root = 'G:\Company files\HR'
linux_root = '/srv/grainhr/hr'
```

The original roster Google sheets are not read on Linux. The server uses `data/roster_inbox`.

## 4. Website sign-in

The website sits behind Cloudflare Access. People sign in there with the company Google account, and GrainHR trusts that sign-in instead of showing its own login button. The check is on when `GRAINHR_SERVER=1`. `GRAINHR_ACCESS_TEAM` and `GRAINHR_ACCESS_AUD` override the team and audience tag built into the server copy.

A copy that is not behind Access can still use its own Google button. Create an OAuth client and do not commit the secrets file:

- Type: Web application
- User type: Internal, so only company Google accounts can sign in
- Redirect URI: `https://hr.<your-domain>/oauth2callback`

On the server, create `/opt/grainhr/.streamlit/secrets.toml` and do not commit it:

```
[auth]
redirect_uri = "https://hr.<your-domain>/oauth2callback"
cookie_secret = "<long random string>"

[auth.google]
client_id = "<client id>"
client_secret = "<client secret>"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

## 5. Cloudflare Tunnel

Add the domain to Cloudflare. Create a tunnel that points `hr.<your-domain>` at `http://127.0.0.1:8501`. Install `cloudflared` as a user service. No port 8501 is opened on the VM firewall.

## 6. Who can sign in

In the private `company.toml`, list Google emails. Three admins see office salaries. HR staff do not.

```
[users."you@company.com"]
name = "Your name"
role = "admin"

[users."assistant@company.com"]
name = "Assistant"
role = "hr"
```

An email that is not listed sees 沒有權限. The website reads the email from the Cloudflare sign-in. On a PC, with no `secrets.toml` and with Access turned off, GrainHR still uses the Windows user name.

## 7. Drive folders

Hiding office pay in the app is not enough if HR can open the files in Drive. After the server's rclone account can read the HR drive, remove HR staff access to:

- `pay_table_admin.xlsx`
- the office payslip folders
- the accounting folder

Admins keep that access. `GrainHR.bat` on a PC still needs Drive access, so office pay is only private on the website.

## 8. Start the app

In `deploy/grainhr.service`, replace `REPLACE` with the GrainHR folder path under the rclone mount. The path has spaces, so leave the quotes in place.


```
systemctl --user enable --now grainhr.service
```

Updates after that: push code to GitHub, SSH to the server, run `deploy/update.sh`.

See `deploy/CUTOVER.md` for the week of running both copies.
