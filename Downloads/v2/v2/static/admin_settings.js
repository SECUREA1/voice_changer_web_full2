(function(){
  async function load(){
    const resp = await fetch('/api/settings');
    if(!resp.ok){ return; }
    const data = await resp.json();
    document.querySelector('[name="api_enabled"]').checked = data.api_enabled === '1';
    document.querySelector('[name="contracts_enabled"]').checked = data.contracts_enabled === '1';
    document.querySelector('[name="policy_level"]').value = data.policy_level || 'standard';
  }

  document.getElementById('settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      api_enabled: document.querySelector('[name="api_enabled"]').checked ? '1' : '0',
      contracts_enabled: document.querySelector('[name="contracts_enabled"]').checked ? '1' : '0',
      policy_level: document.querySelector('[name="policy_level"]').value
    };
    await fetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    alert('Settings saved');
  });

  load();
})();
