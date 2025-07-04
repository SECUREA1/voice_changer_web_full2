let walletAddr = "";
const connectBtn   = document.getElementById('connect-wallet');
const walletSpan   = document.getElementById('wallet-address');
const startBtn     = document.getElementById('start-stream');
const stopBtn      = document.getElementById('stop-stream');
const recStartBtn  = document.getElementById('start-rec');
const recStopBtn   = document.getElementById('stop-rec');
const playBtn      = document.getElementById('play-rec');
const statusBar    = document.getElementById('status');
const player       = document.getElementById('recording');
const playerBlock  = document.getElementById('player-block');
const effectBtns   = document.querySelectorAll('.controls button[data-effect]');

function showWallet(){
  let shown = walletAddr && walletAddr.length>12 ? walletAddr.slice(0,6)+"..."+walletAddr.slice(-6) : walletAddr;
  walletSpan.textContent = walletAddr ? `Wallet: ${shown}` : '';
  document.getElementById('nft-wallet').value = walletAddr || '';
}

connectBtn.onclick = async () => {
  if(window.ethereum){
    try { const acc = await window.ethereum.request({method:'eth_requestAccounts'}); walletAddr = acc[0]; }
    catch{ walletAddr = ''; }
  } else {
    walletAddr = prompt('Paste your wallet address:') || '';
  }
  showWallet();
};

async function post(url, data){
  try {
    const resp = await fetch(url,{method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
    return await resp.json();
  } catch(e){ console.error(e); return {}; }
}

startBtn.onclick = async () => {
  await post('/voice_changer/start_stream', {});
  startBtn.disabled = true;
  stopBtn.disabled = false;
  statusBar.textContent = 'Streaming...';
};

stopBtn.onclick = async () => {
  await post('/voice_changer/stop_stream', {});
  startBtn.disabled = false;
  stopBtn.disabled = true;
  statusBar.textContent = 'Stopped.';
};

recStartBtn.onclick = async () => {
  await post('/voice_changer/start_record', {});
  recStartBtn.disabled = true;
  recStopBtn.disabled = false;
  playBtn.disabled = true;
  statusBar.textContent = 'Recording...';
};

recStopBtn.onclick = async () => {
  const res = await post('/voice_changer/stop_record', {});
  recStartBtn.disabled = false;
  recStopBtn.disabled = true;
  if(res && res.wav){
    const bin = atob(res.wav);
    const buf = new Uint8Array(bin.length);
    for(let i=0;i<bin.length;i++) buf[i]=bin.charCodeAt(i);
    const blob = new Blob([buf], {type:'audio/wav'});
    player.src = URL.createObjectURL(blob);
    playerBlock.style.display='block';
    playBtn.disabled = false;
    document.getElementById('mint-btn').disabled = false;
  }
  statusBar.textContent = 'Recording ready.';
};

playBtn.onclick = () => { player.play(); };

effectBtns.forEach(btn=>{
  btn.onclick = async () => {
    effectBtns.forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    await post('/api/params', {effect: btn.getAttribute('data-effect')});
  };
});

['pitch','speed','volume','echo'].forEach(id=>{
  const el = document.getElementById(id);
  el.oninput = () => {
    const payload = {};
    payload[id === 'pitch' ? 'pitch_shift' : id] = parseFloat(el.value);
    post('/api/params', payload);
  };
});

const mintBtn = document.getElementById('mint-btn');
const mintStatus = document.getElementById('mint-status');

mintBtn.onclick = async () => {
  mintStatus.textContent = '';
  const title = document.getElementById('nft-title').value.trim();
  const chain = document.getElementById('nft-chain').value;
  const wallet = document.getElementById('nft-wallet').value.trim();
  if(!player.src) return; // no audio
  if(!title || !wallet){ mintStatus.textContent='Fill all fields.'; return; }
  mintStatus.textContent = 'Minting...';
  const blob = await (await fetch(player.src)).blob();
  const fd = new FormData();
  fd.append('title', title);
  fd.append('chain', chain);
  fd.append('wallet', wallet);
  fd.append('audio', blob, 'voice.wav');
  try{
    const resp = await fetch('/api/mint-voice', {method:'POST', body:fd});
    const j = await resp.json();
    mintStatus.textContent = j.success ? 'NFT Minted!' : 'Error: '+(j.message||'');
  }catch(e){
    mintStatus.textContent = 'Error.';
  }
};
