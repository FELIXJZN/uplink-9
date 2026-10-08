# Uplink-9 Mobile

The Uplink-9 terminal for iPhone and Apple Watch, forked from the handheld's interface.

- **On its own:** this phone's vitals, node checks from the phone, local notes, the built-in
  holotapes, and two-way messages through an ntfy topic.
- **Linked to your Uplink-9 handheld:** its vitals, USB drives, node pings, VPN tunnel, message threads
  and holotapes, and you can send messages through it.
- **Apple Watch:** three tabs (STATUS, NODES, MSGS). Turn the **Digital Crown** to switch tabs; tap to refresh.
  The Watch gets its data from the iPhone app.

## Building without a Mac

iPhone and Watch apps can only be compiled by Apple's tools on a Mac. This repo lets GitHub's cloud Macs
do it, so everything below works from Windows.

### 1. Check that it builds (free)

1. Create a repo on GitHub (for example `uplink-9-mobile`) and push this folder to it.
2. Open the **Actions** tab. The **Build** workflow runs on every push and compiles the iPhone and Watch
   app on a cloud Mac. A green tick means the code builds. If it's red, open the run and copy the errors.

This step needs no Apple account.

### 2. Get it onto your iPhone and Watch (Apple Developer Program, $99/year)

Installing an app on an iPhone needs it signed by Apple. Without a Mac, the way to do that is
TestFlight, which needs a paid Apple Developer account.

1. **Join** the Apple Developer Program at developer.apple.com (takes up to a day or two to activate).
2. **Pick a bundle ID**, your own reverse domain, for example `be.4rden.uplink9`.
3. **Create the app** in App Store Connect: *Apps > + > New App*, platform iOS, name "Uplink-9"
   (the name must be unique on the store; add something if it's taken), and register your bundle ID
   when it asks (*Certificates, IDs & Profiles > Identifiers > +*).
4. **Make an API key:** App Store Connect > *Users and Access > Integrations > App Store Connect API*
   > *+*, access **Admin**. Download the `.p8` file (you can only download it once) and note the
   **Key ID** and the **Issuer ID** shown on that page.
5. **Find your Team ID:** developer.apple.com > *Account > Membership details*.
6. **Add them to GitHub:** in your repo, *Settings > Secrets and variables > Actions*.

   | Secret | Value |
   |---|---|
   | `APPLE_TEAM_ID` | your Team ID |
   | `ASC_KEY_ID` | the Key ID |
   | `ASC_ISSUER_ID` | the Issuer ID |
   | `ASC_KEY_P8` | the whole text of the `.p8` file, including the BEGIN and END lines |

   | Variable | Value |
   |---|---|
   | `BUNDLE_ID` | your bundle ID, for example `be.4rden.uplink9` |
   | `TESTFLIGHT` | `on` |

7. **Run it:** *Actions > Build > Run workflow*. After the compile step, the TestFlight step signs and
   uploads the app. Apple takes 10–30 minutes to process it.
8. **Install:** get the **TestFlight** app on your iPhone, sign in with the same Apple ID, and install
   Uplink-9. The Watch app installs with it (or from the Watch app on your iPhone, under *Available Apps*).
   The first time, App Store Connect may ask you to fill in export compliance; the app already says it
   uses no special encryption.

Every push to `main` after that uploads a new build with a higher build number.

## Pairing with the handheld

On the Uplink-9 handheld (beta 0.11 or newer), as admin:

1. **SETTINGS > PHONE LINK > LINK: ON**
2. **SHOW PAIRING CODE**
3. Point the iPhone **Camera** app at the code and tap the banner. Uplink-9 opens and asks to pair.

You can also type the address, port (8909) and token under **[SETUP]**.

The phone talks to the handheld over plain HTTP on its Tailscale address (100.x.x.x) or home IP. With
Tailscale on both, it works from anywhere. Only someone with the token can connect, and
**NEW PAIRING CODE** on the handheld locks out every paired phone.

## Without the handheld

- **Nodes:** a phone can't ping, so it opens a connection to each node instead (SSH, port 22 by default).
  Edit the list in **[SETUP]**. With Tailscale on, the names `pve-1` etc. resolve through MagicDNS.
- **ntfy:** set a topic URL in **[SETUP]** (for example `https://ntfy.sh/your-secret-topic`) and an NTFY
  thread appears in LOGS: what you send goes to the topic, and replies come back every 20 seconds.
- **Notes:** the PHONE NOTES thread stays on the phone.

## Layout

```
project.yml          XcodeGen definition (the build turns it into Uplink9.xcodeproj)
Shared/              models matching the handheld's API, and the terminal look
iOS/                 iPhone app: store, services (link, ntfy, node checks, sounds, Watch bridge), screens
Watch/               Watch app: Digital Crown tabs
.github/workflows/   cloud build and TestFlight upload
```

## Limits

- The Watch shows what the iPhone last sent. Open the iPhone app now and then (it refreshes every few
  seconds while open); the Watch keeps the last data and shows when it was updated.
- The phone can read status and send messages, but can't mount or eject drives, switch the VPN, or
  change settings on the handheld. Those stay on the device, behind the admin login.
- This code was written without a Mac, so the first cloud build is also its first real compile. If it
  fails, the error list from the Actions run is all that's needed to fix it.
