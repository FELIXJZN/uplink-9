# Uplink-9 Mobile

The Uplink-9 terminal for iPhone and Apple Watch, forked from the handheld's interface.

- **On its own:** this phone's vitals, node checks from the phone, local notes, the built-in
  holotapes, and two-way messages through an ntfy topic.
- **PERSONAL:** your Vikunja tasks as quests on a map and a radar (see below).
- **Linked to your Uplink-9 handheld:** its vitals, USB drives, node pings, VPN tunnel, message threads
  and holotapes, and you can send messages through it.
- **Apple Watch:** three tabs (STATUS, NODES, MSGS). Turn the **Digital Crown** to switch tabs; tap to refresh.
  The Watch gets its data from the iPhone app.

## PERSONAL tab: quests

Your open Vikunja tasks as quests, straight from your Vikunja server (not through the handheld).

- **MAP:** Apple's built-in map (no API key or account needed), dark and muted, with a quest marker
  wherever tasks are. An amber marker has an overdue task. Tap a marker to open its quests.
- **RADAR:** no map and no network at all: quests plotted by distance and direction from you,
  turning with the phone. [RANGE] cycles 500 m, 2 km, 10 km and 50 km.
- **QUESTS:** the list, nearest first, with the unplaced ones below.
- **Quest card:** navigate there in Apple Maps, show it on the map, pin it to a place, open it in
  Vikunja, or mark it done (written back to Vikunja).
- **Nearby alert:** within 150 m of a quest the phone chirps and says so (while the app is open).

**How a task gets on the map**, first match wins:

1. You pinned it from the phone (kept on the phone; Vikunja isn't changed).
2. Its description holds a location: `geo:50.8503,4.3517`, or a pasted Apple Maps or Google Maps link.
3. One of its labels has the same name as a saved place. Mark places on the map with the crosshair
   and [MARK PLACE], for example `STUDIO`, then give tasks the label `STUDIO` in Vikunja.

**Setup:** in Vikunja, *Settings > API Tokens*, make a token with access to tasks and projects. In the
app, **[SETUP] > VIKUNJA QUESTS**: the address (for example `https://vikunja.your-tailnet.ts.net`), the token
(stored in the iPhone keychain), and optionally one project ID. Tailscale must be on to reach it.

## Building without a Mac

iPhone and Watch apps can only be compiled by Apple's tools on a Mac. GitHub's cloud Macs do it, so
everything below works from Windows. This app lives in the `mobile/` folder of the uplink-9 repo, and the
**iPhone app** workflow (`.github/workflows/ios.yml`) builds it on every push that changes `mobile/`.

### 1. Get the app file

On GitHub: **Actions > iPhone app >** the newest run with a green tick **> Artifacts > Uplink9-ipa**.
That downloads a zip with `Uplink9.ipa` inside: the app, compiled for real iPhones but not signed yet.
(**Run workflow** on that page starts a fresh build by hand.)

### 2a. Install it with a free Apple ID (Sideloadly, from Windows)

1. On the PC, install **iTunes** and **iCloud** from apple.com (the website versions, not the Microsoft
   Store ones), then **Sideloadly** from sideloadly.io.
2. Plug the iPhone in with a cable, unlock it and tap **Trust**.
3. In Sideloadly, drop `Uplink9.ipa` on the window, type your Apple ID and press **Start**. It signs the
   app with your Apple ID and installs it.
4. On the iPhone, first time only:
   - **Settings > Privacy & Security > Developer Mode** on (the phone restarts and asks to confirm)
   - **Settings > General > VPN & Device Management >** your Apple ID **> Trust**
5. Open Uplink-9.

With a free Apple ID the app stops opening after **7 days**: run Sideloadly again to renew it (your
settings stay). The **Watch app may not come along** with a free Apple ID; for the Watch, use TestFlight.

### 2b. Or TestFlight (Apple Developer Program, $99/year)

No 7-day limit, the Watch app installs too, and updates arrive by themselves.

1. **Join** the Apple Developer Program at developer.apple.com (takes up to a day or two to activate).
2. **Pick a bundle ID**, your own reverse domain, for example `be.4rden.uplink9`.
3. **Create the app** in App Store Connect: *Apps > + > New App*, platform iOS, name "Uplink-9"
   (the name must be unique on the store; add something if it's taken), and register your bundle ID
   when it asks (*Certificates, IDs & Profiles > Identifiers > +*).
4. **Make an API key:** App Store Connect > *Users and Access > Integrations > App Store Connect API*
   > *+*, access **Admin**. Download the `.p8` file (you can only download it once) and note the
   **Key ID** and the **Issuer ID** shown on that page.
5. **Find your Team ID:** developer.apple.com > *Account > Membership details*.
6. **Add them to GitHub:** in the uplink-9 repo, *Settings > Secrets and variables > Actions*.

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

7. **Run it:** *Actions > iPhone app > Run workflow*. After the build, the TestFlight step signs and
   uploads the app. Apple takes 10–30 minutes to process it.
8. **Install:** get the **TestFlight** app on your iPhone, sign in with the same Apple ID, and install
   Uplink-9. The Watch app installs with it (or from the Watch app on your iPhone, under *Available Apps*).

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
../.github/workflows/ios.yml   cloud build (.ipa) and TestFlight upload
```

## Limits

- The Watch shows what the iPhone last sent. Open the iPhone app now and then (it refreshes every few
  seconds while open); the Watch keeps the last data and shows when it was updated.
- The phone can read status and send messages, but can't mount or eject drives, switch the VPN, or
  change settings on the handheld. Those stay on the device, behind the admin login.
- This code was written without a Mac, so the first cloud build is also its first real compile. If it
  fails, the error list from the Actions run is all that's needed to fix it.
