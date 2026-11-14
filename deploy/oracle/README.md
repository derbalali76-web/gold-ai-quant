# Always-on free server (Oracle Cloud Always Free)

Render's free plan sleeps; an Oracle Cloud "Always Free" VM stays on at no cost.

1. Create an Oracle Cloud account (Always Free). Oracle asks for a card for identity verification; Always Free
   resources are not charged. Pick a home region close to you (it cannot be changed later).
2. Create a VM instance: image **Ubuntu**, shape **VM.Standard.A1.Flex** (Ampere, e.g. 1 OCPU / 6 GB) or
   **VM.Standard.E2.1.Micro**. Download the SSH key. Note the public IP.
3. Networking → your VCN → Security List → add **Ingress rules** for TCP **80** and **443** from `0.0.0.0/0`.
4. Connect: `ssh -i key ubuntu@PUBLIC_IP`, then:
   ```
   curl -fsSL -H "Authorization: token YOUR_GITHUB_TOKEN" \
     https://raw.githubusercontent.com/derbalali76-web/gold-ai-quant/main/deploy/oracle/setup.sh -o setup.sh
   bash setup.sh
   ```
5. Put the printed `https://…sslip.io` address in the app settings. Keep Render as a backup or delete it.

The server updates itself every 30 minutes from `main`.
