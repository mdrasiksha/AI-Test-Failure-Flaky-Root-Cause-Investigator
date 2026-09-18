(() => {
  const valid = (file, extension) => file.name.toLowerCase().endsWith(extension);
  document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(item => item.classList.toggle('active', item === tab));
    document.querySelectorAll('.panel').forEach(panel => panel.classList.toggle('active', panel.dataset.panel === tab.dataset.tab));
  }));
  document.querySelectorAll('.dropzone').forEach(zone => {
    const input = zone.querySelector('input'); const output = zone.querySelector('output');
    const show = () => output.textContent = input.files.length ? [...input.files].map((f, i) => `${i + 1}. ${f.name}`).join('\n') : 'No file selected';
    input.addEventListener('change', show);
    ['dragenter','dragover'].forEach(name => zone.addEventListener(name, e => { e.preventDefault(); zone.classList.add('dragging'); }));
    ['dragleave','drop'].forEach(name => zone.addEventListener(name, e => { e.preventDefault(); zone.classList.remove('dragging'); }));
    zone.addEventListener('drop', e => { input.files = e.dataTransfer.files; show(); });
  });
  document.querySelectorAll('form.panel').forEach(form => form.addEventListener('submit', event => {
    const error = form.querySelector('.form-error'); error.textContent = '';
    const history = form.dataset.panel === 'history'; const trace = form.dataset.panel === 'trace';
    const primary = form.querySelector('.dropzone input'); const files = [...primary.files];
    if (!files.length) error.textContent = 'Choose a file before starting analysis.';
    else if (history && files.length < 2) error.textContent = 'Choose at least two XML reports in chronological order.';
    else if (!files.every(file => valid(file, trace ? '.zip' : '.xml'))) error.textContent = `Choose only ${trace ? '.zip' : '.xml'} files.`;
    const junit = form.querySelector('[name=junit_file]');
    if (!error.textContent && junit?.files.length && !valid(junit.files[0], '.xml')) error.textContent = 'The optional JUnit report must be an .xml file.';
    if (error.textContent) { event.preventDefault(); return; }
    form.querySelector('button[type=submit]').disabled = true;
    const ai = form.querySelector('[name=use_ai]')?.checked;
    form.querySelector('.loading').textContent = ai ? 'Analyzing evidence and investigating likely root cause...' : form.dataset.loading;
  }));
  document.querySelectorAll('.copy-button').forEach(button => button.addEventListener('click', async () => {
    await navigator.clipboard.writeText(button.closest('.ai-section').querySelector('.suggested-code').textContent);
    button.textContent = 'Copied';
  }));
  document.querySelectorAll('[data-feedback]').forEach(panel => {
    let useful = null; let sent = false;
    const status = panel.querySelector('[data-feedback-status]');
    const detail = panel.querySelector('.feedback-detail');
    const send = async (feedbackText = null) => {
      if (sent) return;
      try {
        const response = await fetch('/feedback', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({useful, feedback_text: feedbackText || null, analysis_type: panel.dataset.analysisType})});
        if (!response.ok) throw new Error('unavailable');
        sent = true; status.textContent = 'Thanks for the feedback.';
        panel.querySelectorAll('button').forEach(button => { button.disabled = true; });
      } catch (_) { status.textContent = 'Feedback is currently unavailable. Your analysis is unaffected.'; }
    };
    panel.querySelectorAll('[data-useful]').forEach(button => button.addEventListener('click', () => {
      if (sent || useful !== null) return;
      useful = button.dataset.useful === 'true';
      detail.hidden = false;
      status.textContent = 'Optionally add a note, then submit your feedback.';
    }));
    panel.querySelector('[data-submit-detail]').addEventListener('click', async () => {
      if (sent) return;
      await send(panel.querySelector('textarea').value);
    });
  });
})();
