# Deploying the collector (Day 1)

Goal: the collector runs 24/7 and you can prove it did. Every hour it is down is data you can never get back, and your final claim ("a continuous live record") depends on it.

## Read this before choosing Oracle

Verified against Oracle's docs (docs.oracle.com, Always Free Resources page) and an InfoQ report, checked 23 Nov 2026:

- Always Free Arm instances (VM.Standard.A1.Flex) are now **2 OCPUs and 12 GB total**. The limit was 4 OCPUs and 24 GB until 15 June 2026, per InfoQ. This is plenty for the collector.
- The AMD option (VM.Standard.E2.1.Micro) has **1 GB of RAM**. It runs the collector, but leaves little room for anything else.
- **Idle reclamation:** Oracle may reclaim an Always Free instance if, over 7 days, CPU (95th percentile), network, and (A1 only) memory are all below 20%. **Your collector will look idle** (a few percent CPU, well under 1 Mbps).
- The docs do not say clearly whether Pay As You Go (upgraded) accounts are exempt. Oracle says Always Free resources are available to "free or paid" accounts and are not charged after upgrade; it does not confirm reclamation behaviour for paid accounts. Ask Oracle support if you rely on it.
- Capacity: new Always Free A1 instances are often "out of capacity" in busy regions; retrying later or choosing another availability domain usually works.

**What I'd do:** use Oracle if you like, but treat it as unreliable. (1) Upgrade to Pay As You Go if you are comfortable adding a card (Always Free resources stay free), (2) copy your data off the server every day (step 8), and (3) check the health of the collector daily. If Oracle stops the instance, you lose a few days and not the whole record. A small paid VPS from any mainstream provider, typically a few dollars a month, avoids the idle-policy risk entirely and is a fair alternative. Pricing changes; check before you buy.

Do not install "keep-alive" load generators to trick the idle detector; that is gaming a provider's policy and can get the account actioned.

## Steps (Ubuntu 22.04 or 24.04, x86 or Arm)

1. **Create the instance.** Shape: A1.Flex with 1 OCPU and 6 GB, or the Micro. Image: Ubuntu. Add your SSH public key. Keep the default boot volume (about 50 GB). In your home region only.
2. **Log in and install basics.**
   ```
   ssh ubuntu@<public-ip>
   sudo apt update && sudo apt install -y python3-venv python3-pip chrony
   chronyc tracking        # "Leap status: Normal" and a small "System time" offset
   ```
   Time sync matters: `recv_ns` is the only clock the depth stream gives you.
3. **Copy the code.** From your laptop, inside the unzipped project folder:
   ```
   scp -r collector ubuntu@<public-ip>:~/deeplob/
   ```
4. **Install dependencies.**
   ```
   cd ~/deeplob
   python3 -m venv venv
   venv/bin/pip install -r collector/requirements.txt
   ```
5. **Probe before you record.** This prints 5 raw messages and also proves the server can reach Binance.
   ```
   cd collector && ../venv/bin/python collector.py --probe 5
   ```
   - You should see JSON lines like `{"stream":"btcusdt@depth20@100ms","data":{...}}`.
   - **Send me the first two lines** (or tell me if it errors). I could not verify the live format from my own environment, and the parser assumes `lastUpdateId`, `bids`, `asks` and the combined-stream wrapper.
   - If the connection is refused or returns an HTTP error, Binance may block that region. Try the market-data-only host by editing `build_url` to `wss://data-stream.binance.vision/stream?...`, or create the instance in another region, or tell me and we switch exchange.
6. **Run the tests once on the server** (confirms the Arm/x86 build works): `../venv/bin/python -m pytest -q`
7. **Install as a service so it survives reboots and crashes.**
   ```
   sudo cp lob-collector.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now lob-collector
   journalctl -u lob-collector -f        # Ctrl-C to leave; look for "event connect"
   ```
   If your Linux user is not `ubuntu`, edit the three paths in the unit file.
8. **Copy data off the server daily** (from your laptop; safe to repeat):
   ```
   rsync -av --ignore-existing ubuntu@<public-ip>:~/deeplob/data/ ~/lob-backup/
   ```
9. **Verify after 15 minutes:**
   ```
   ls ~/deeplob/data/book/BTCUSDT/$(date -u +%F) | wc -l     # a handful of part-*.parquet files
   tail -5 ~/deeplob/data/events.jsonl                       # connect, no repeating disconnects
   du -sh ~/deeplob/data                                     # grows by roughly 0.3-0.5 GB per day
   ```

## Safety notes

- This only reads public market data. It needs **no API key**; never put exchange keys on this machine.
- Only port 22 needs to be open inbound. Restrict it to your own IP in the Oracle security list if you can.
- Storage: roughly 0.3 to 0.5 GB per day for two symbols (my upper-bound estimate from synthetic data; we'll measure the real number), so 8 weeks fits easily in 50 GB. Delete nothing; copy off weekly.
