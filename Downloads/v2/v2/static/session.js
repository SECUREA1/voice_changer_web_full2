(function(){
  const CHAIN_KEY = 'mixer_current_chain';
  const WALLET_KEY = 'mixer_current_wallet';
  const USER_KEY   = 'mixer_username';
  const USER_DATA_KEY = 'session_user';

  function loadUserData(){
    try{ return JSON.parse(localStorage.getItem(USER_DATA_KEY)) || {}; }catch{ return {}; }
  }

  function saveUserData(obj){
    localStorage.setItem(USER_DATA_KEY, JSON.stringify(obj || {}));
  }

  const storedData = loadUserData();
  const context = {
    username: window.APP_USER || storedData.username || localStorage.getItem(USER_KEY) || '',
    wallet: window.APP_WALLET || storedData.wallet || localStorage.getItem(WALLET_KEY) || '',
    chain: localStorage.getItem(CHAIN_KEY) || ''
  };

  if(window.APP_WALLET){
    localStorage.setItem(WALLET_KEY, window.APP_WALLET);
    context.wallet = window.APP_WALLET;
  }
  if(window.APP_USER){
    localStorage.setItem(USER_KEY, window.APP_USER);
    context.username = window.APP_USER;
  }
  if(window.APP_CHAIN){
    localStorage.setItem(CHAIN_KEY, window.APP_CHAIN);
    context.chain = window.APP_CHAIN;
  }

  if(window.APP_WALLET || window.APP_USER){
    saveUserData({username: context.username, wallet: context.wallet});
  }

  window.APP_CONTEXT = context;

  // Previously the session data was cleared whenever the user navigated away
  // from a page. This prevented the wallet and username from persisting across
  // the app. The automatic logout has been removed so that the wallet and
  // rewards remain available while browsing different pages. To log out, the
  // user must now explicitly visit the `/logout` route.  A global logout
  // button is injected on every page and will end the server session while
  // preserving any wallet and user details stored locally. This allows the
  // next login to prefill those values, similar to how the rewards bar
  // remembers a wallet across visits.

  function performLogout(){
    fetch('/logout', {method: 'POST'})
      .finally(() => {
        // Attempt to close the current tab; fallback to redirect
        window.open('', '_self');
        window.close();
        window.location.href = '/';
      });
  }

  document.addEventListener('DOMContentLoaded', () => {
    const container = document.createElement('div');
    Object.assign(container.style, {
      position: 'fixed',
      top: '10px',
      left: '10px',
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'center',
      gap: '8px',
      zIndex: 10000,
      fontFamily: 'Segoe UI, sans-serif'
    });

    const clock = document.createElement('span');
    clock.id = 'live-clock';
    Object.assign(clock.style, {
      color: '#ffd700',
      fontWeight: 'bold',
      fontSize: '1.05em'
    });
    container.appendChild(clock);

    const logoutBtn = document.createElement('button');
    logoutBtn.id = 'logout-btn';
    logoutBtn.textContent = 'Logout';
    Object.assign(logoutBtn.style, {
      padding: '8px 14px',
      background: '#b30000',
      color: '#ffd700',
      border: '2px solid #ffd700',
      borderRadius: '8px',
      cursor: 'pointer'
    });
    logoutBtn.addEventListener('click', performLogout);
    container.appendChild(logoutBtn);

    const chatBtn = document.createElement('button');
    chatBtn.id = 'chat-toggle-btn';
    chatBtn.textContent = 'Chat';
    Object.assign(chatBtn.style, {
      padding: '8px 14px',
      background: '#b30000',
      color: '#ffd700',
      border: '2px solid #ffd700',
      borderRadius: '8px',
      cursor: 'pointer'
    });
    container.appendChild(chatBtn);

    document.body.appendChild(container);
    function updateClock(){
      clock.textContent = new Date().toLocaleTimeString();
    }
    updateClock();
    setInterval(updateClock, 1000);

    // Inject live chat for logged-in users
    if(context.username){
      const sio = document.createElement('script');
      // Load Socket.IO client from the official CDN
      sio.src = 'https://cdn.socket.io/4.7.5/socket.io.min.js';
      document.body.appendChild(sio);
      const script = document.createElement('script');
      script.src = '/static/chat.js';
      document.body.appendChild(script);
      chatBtn.addEventListener('click', () => {
        if(window.initChatBox){
          window.initChatBox();
        }
      });
      // keep socket connection alive for active user tracking
      sio.onload = () => {
        const socket = io();
        socket.on('connect', () => {
          socket.emit('user_ping');
          setInterval(() => socket.emit('user_ping'), 10000);
        });
      };
    } else {
      chatBtn.style.display = 'none';
    }
  });
})();
