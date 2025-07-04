// mixer.js
document.addEventListener("DOMContentLoaded", () => {
  const voiceInput = document.getElementById("voice-file");
  const beatInput = document.getElementById("beat-file");
  const fxInput = document.getElementById("fx-file");

  document.getElementById("mint-nft").addEventListener("click", async () => {
    const wallet = document.getElementById("wallet-address").textContent;
    const formData = new FormData();
    formData.append("walletAddress", wallet);
    formData.append("chain", "ethereum");
    if (voiceInput.files[0]) formData.append("voice", voiceInput.files[0]);
    if (beatInput.files[0]) formData.append("beat", beatInput.files[0]);
    if (fxInput.files[0]) formData.append("fx", fxInput.files[0]);

    const res = await fetch("/api/mint-nft", { method: "POST", body: formData });
    const json = await res.json();
    document.getElementById("mint-status").innerText = json.message;
  });
});
// mixer.js
document.addEventListener("DOMContentLoaded", () => {
  const voiceInput = document.getElementById("voice-file");
  const beatInput = document.getElementById("beat-file");
  const fxInput = document.getElementById("fx-file");

  const voicePreview = document.getElementById("voice-preview");
  const beatPreview = document.getElementById("beat-preview");
  const fxPreview = document.getElementById("fx-preview");

  const connectBtn = document.getElementById("connect-wallet");
  const walletDisplay = document.getElementById("wallet-address");
  const mintBtn = document.getElementById("mint-nft");
  const statusBox = document.getElementById("mint-status");

  let walletAddress = null;
  let chain = "solana"; // default chain; can be replaced with dropdown if added

  // Auto-preview selected audio
  voiceInput.addEventListener("change", () => {
    voicePreview.src = URL.createObjectURL(voiceInput.files[0]);
  });
  beatInput.addEventListener("change", () => {
    beatPreview.src = URL.createObjectURL(beatInput.files[0]);
  });
  fxInput.addEventListener("change", () => {
    fxPreview.src = URL.createObjectURL(fxInput.files[0]);
  });

  // Connect Wallet (EVM, Solana, Cardano)
  connectBtn.addEventListener("click", async () => {
    try {
      if (window.solana && window.solana.isPhantom) {
        const resp = await window.solana.connect();
        walletAddress = resp.publicKey.toString();
        chain = "solana";
      } else if (window.ethereum) {
        const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
        walletAddress = accounts[0];
        chain = "ethereum";
      } else if (window.cardano && window.cardano.nami) {
        const enabled = await window.cardano.nami.enable();
        const addr = await enabled.getUsedAddresses();
        walletAddress = addr[0];
        chain = "cardano";
      } else {
        alert("No compatible wallet found.");
        return;
      }

      walletDisplay.textContent = `Connected: ${walletAddress}`;
      connectBtn.disabled = true;
    } catch (err) {
      console.error("Wallet connection error:", err);
      alert("Failed to connect wallet.");
    }
  });

  // Mint NFT
  mintBtn.addEventListener("click", async () => {
    if (!walletAddress) {
      alert("Connect your wallet first.");
      return;
    }

    const formData = new FormData();
    formData.append("walletAddress", walletAddress);
    formData.append("chain", chain);

    if (voiceInput.files[0]) formData.append("voice", voiceInput.files[0]);
    if (beatInput.files[0]) formData.append("beat", beatInput.files[0]);
    if (fxInput.files[0]) formData.append("fx", fxInput.files[0]);

    statusBox.textContent = "⏳ Uploading and minting...";

    try {
      const res = await fetch("/api/mint-nft", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();

      if (data.status === "success") {
        statusBox.textContent = `✅ ${data.message}`;
      } else {
        statusBox.textContent = `❌ ${data.message}`;
      }
    } catch (err) {
      console.error("Mint error:", err);
      statusBox.textContent = "❌ Failed to mint NFT.";
    }
  });

  // Optional: Handle preview-mix button logic (just plays all selected previews simultaneously)
  document.getElementById("preview-mix").addEventListener("click", () => {
    [voicePreview, beatPreview, fxPreview].forEach(el => {
      if (el.src) {
        el.currentTime = 0;
        el.play();
      }
    });
  });
});
