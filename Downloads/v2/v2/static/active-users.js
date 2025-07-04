(function(){
  const socket = io();
  let chart;
  const labels = [];
  const points = [];

  function update(data){
    const list = document.getElementById('user-list');
    list.innerHTML = '';
    data.users.forEach(u => {
      const li = document.createElement('li');
      li.textContent = u;
      list.appendChild(li);
    });
    document.getElementById('user-count').textContent = `${data.count} users online`;

    const now = new Date().toLocaleTimeString();
    labels.push(now);
    points.push(data.count);
    if(labels.length > 20){ labels.shift(); points.shift(); }
    if(!chart){
      const ctx = document.getElementById('user-chart').getContext('2d');
      chart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets: [{ label: 'Active Users', data: points, borderColor: '#ffd700', fill: false }] },
        options: { scales: { y: { beginAtZero: true, precision: 0 } } }
      });
    } else {
      chart.update();
    }
  }

  socket.on('connect', () => {
    socket.emit('user_ping');
    setInterval(() => socket.emit('user_ping'), 10000);
  });
  socket.on('active_user_update', update);
})();
