(function(){
  let chatSocket = null;
  function createBox(){
    const ctx = window.APP_CONTEXT || {};
    const box = document.createElement('div');
    box.id = 'chat-box';
    Object.assign(box.style, {
      position: 'fixed',
      top: '0',
      bottom: '0',
      right: '0',
      width: '33%',
      maxWidth: '420px',
      background: '#1a1a1a',
      color: '#ffd700',
      borderLeft: '2px solid #ffd700',
      padding: '10px',
      fontSize: '14px',
      zIndex: 9999,
      display: 'flex',
      flexDirection: 'column',
      boxSizing: 'border-box'
    });
    if(window.innerWidth < 600){
      box.style.width = '100%';
      box.style.maxWidth = 'none';
    }
    box.innerHTML = '<div id="chat-feed" style="overflow-y:auto;flex:1;margin-bottom:4px;background:#111;padding:4px;"></div>' +
      '<form id="chat-form" style="display:flex;gap:4px;">' +
      '<input id="chat-input" style="flex:1;padding:4px;background:#222;border:1px solid #555;color:#ffd700;" />' +
      '<button style="padding:4px 8px;background:#b30000;color:#ffd700;border:1px solid #ffd700;">Send</button>' +
      '</form>';
    document.body.appendChild(box);

    const feed = box.querySelector('#chat-feed');
    const form = box.querySelector('#chat-form');
    const input = box.querySelector('#chat-input');
    const sendAllowed = !!ctx.username;
    const socket = io();
    chatSocket = socket;
    socket.on('connect', () => {
      socket.emit('get_chat_history');
    });
    function appendMsg(data){
      const msg = document.createElement('div');
      msg.textContent = `${data.user}: ${data.message}`;
      msg.style.color = '#00a0ff';
      msg.style.textShadow = '0 0 4px gold';
      feed.appendChild(msg);
      feed.scrollTop = feed.scrollHeight;
    }
    socket.on('chat_history', history => {
      feed.innerHTML = '';
      history.forEach(appendMsg);
    });
    socket.on('chat_message', appendMsg);
    socket.on('chat_error', msg => {
      alert(msg);
    });
    if(!sendAllowed){
      input.disabled = true;
      input.placeholder = 'Login required to chat';
    }
    form.addEventListener('submit', e => {
      e.preventDefault();
      if(!sendAllowed){
        alert('Login required to chat');
        return;
      }
      const txt = input.value.trim();
      if(txt){
        socket.emit('chat_message', {message: txt});
        input.value = '';
      }
    });
    return box;
  }

    window.initChatBox = function(){
      let box = document.getElementById('chat-box');
      if(box){
        const showing = box.style.display === 'none';
        box.style.display = showing ? 'block' : 'none';
        if(showing && chatSocket){
          chatSocket.emit('get_chat_history');
        }
        return;
      }
      createBox();
    };
  })();
