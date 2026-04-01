// ═══════════════════════════════════════════════
    // 全局状态
    // ═══════════════════════════════════════════════
    let currentEventSource = null;
    let stepCount = 0;
    let currentTaskId = null;
    let selectedProvider = '';
    let MODEL_PRESETS = {};

    // 对话状态
    let chatHistory = [];  // [{role,content}]
    let chatMode = 'refine';
    let isChatLoading = false;

    // 知识库状态
    let selectedToolName = null;
    let knowledgeData = [];
    let benignWhitelistData = null;
    let mcpRegistryData = [];

    // 自定义快捷指令（按 OS 分组）
    // 结构：{ linux: [{label, task}, ...], windows: [...] }
    let customTags = { linux: [], windows: [] };
    const CUSTOM_TAGS_KEY = 'ai_agent_custom_tags';

    // ═══════════════════════════════════════════════
    // 工具函数
    // ═══════════════════════════════════════════════
    function esc(s) {
      return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    }

    function toast(msg, type = 'ok', duration = 3000) {
      const el = document.getElementById('toast');
      el.textContent = msg;
      el.className = `toast show ${type}`;
      clearTimeout(el._t);
      el._t = setTimeout(() => el.classList.remove('show'), duration);
    }

    let finalAnswerRaw = '';

    function copyText(text) {
      const value = String(text || '');
      if (!value) {
        toast('没有可复制的内容', 'fail');
        return;
      }

      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(value).then(() => {
          toast('已复制到剪贴板');
        }).catch(() => {
          fallbackCopyText(value);
        });
        return;
      }

      fallbackCopyText(value);
    }

    function fallbackCopyText(text) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', 'readonly');
      ta.style.position = 'fixed';
      ta.style.top = '-1000px';
      ta.style.left = '-1000px';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      ta.setSelectionRange(0, ta.value.length);

      try {
        const ok = document.execCommand('copy');
        ta.remove();
        if (ok) {
          toast('已复制到剪贴板');
        } else {
          promptCopyText(text);
        }
      } catch (e) {
        ta.remove();
        promptCopyText(text);
      }
    }

    function promptCopyText(text) {
      window.prompt('当前页面无法直接写入剪贴板，请手动复制下面内容：', text);
      toast('请在弹窗中手动复制', 'fail', 4000);
    }

    function renderInlineMarkdown(text) {
      return esc(text)
        .replace(/`([^`\n]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/__([^_]+)__/g, '<strong>$1</strong>');
    }

    function renderMarkdown(text) {
      const source = String(text || '').replace(/\r\n/g, '\n');
      if (!source.trim()) return '<p>任务已完成</p>';

      const lines = source.split('\n');
      const html = [];
      let inCodeBlock = false;
      let codeLines = [];
      let listType = null;

      function closeList() {
        if (listType) {
          html.push(listType === 'ol' ? '</ol>' : '</ul>');
          listType = null;
        }
      }

      function closeCodeBlock() {
        if (inCodeBlock) {
          html.push(`<pre><code>${esc(codeLines.join('\n'))}</code></pre>`);
          inCodeBlock = false;
          codeLines = [];
        }
      }

      for (const line of lines) {
        if (line.trim().startsWith('```')) {
          closeList();
          if (inCodeBlock) {
            closeCodeBlock();
          } else {
            inCodeBlock = true;
            codeLines = [];
          }
          continue;
        }

        if (inCodeBlock) {
          codeLines.push(line);
          continue;
        }

        if (!line.trim()) {
          closeList();
          continue;
        }

        const heading = line.match(/^(#{1,4})\s+(.*)$/);
        if (heading) {
          closeList();
          const level = heading[1].length;
          html.push(`<h${level}>${renderInlineMarkdown(heading[2].trim())}</h${level}>`);
          continue;
        }

        if (/^\s*---+\s*$/.test(line) || /^\s*\*\*\*+\s*$/.test(line)) {
          closeList();
          html.push('<hr>');
          continue;
        }

        const ordered = line.match(/^\s*\d+\.\s+(.*)$/);
        if (ordered) {
          if (listType !== 'ol') {
            closeList();
            html.push('<ol>');
            listType = 'ol';
          }
          html.push(`<li>${renderInlineMarkdown(ordered[1].trim())}</li>`);
          continue;
        }

        const unordered = line.match(/^\s*[-*]\s+(.*)$/);
        if (unordered) {
          if (listType !== 'ul') {
            closeList();
            html.push('<ul>');
            listType = 'ul';
          }
          html.push(`<li>${renderInlineMarkdown(unordered[1].trim())}</li>`);
          continue;
        }

        closeList();
        html.push(`<p>${renderInlineMarkdown(line)}</p>`);
      }

      closeList();
      closeCodeBlock();
      return html.join('');
    }

    function setFinalAnswer(text) {
      finalAnswerRaw = String(text || '');
      document.getElementById('finalAnswer').innerHTML = renderMarkdown(finalAnswerRaw);
    }

    // ═══════════════════════════════════════════════
    // 事件委托 - 处理推荐任务按钮点击
    // ═══════════════════════════════════════════════
    document.addEventListener('click', function (e) {
      if (e.target && e.target.classList.contains('use-btn')) {
        let taskText = e.target.getAttribute('data-task');
        if (taskText) {
          // 尝试 base64 解码（如果包含中文等特殊字符）
          try {
            taskText = decodeURIComponent(escape(atob(taskText)));
          } catch (err) {
            console.log('base64 解码失败，使用原始值:', err);
          }
          console.log('复制任务:', taskText);
          useRecommendedTask(taskText);
        } else {
          console.error('按钮没有找到 data-task 属性');
        }
      }

      if (e.target && e.target.classList.contains('tag-del')) {
        e.stopPropagation();
        const idx = Number(e.target.getAttribute('data-idx'));
        if (!Number.isNaN(idx)) deleteCustomTag(e, idx);
        return;
      }

      const customTag = e.target && e.target.closest('.custom-tag');
      if (customTag) {
        const encodedTask = customTag.getAttribute('data-task');
        if (encodedTask) {
          try {
            setTask(decodeURIComponent(escape(atob(encodedTask))));
          } catch (err) {
            console.error('自定义快捷指令解码失败:', err);
            toast('快捷指令解析失败', 'fail');
          }
        }
      }
    });

    // ═══════════════════════════════════════════════
    // 标签页切换
    // ═══════════════════════════════════════════════
    function switchTab(name, btn) {
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.getElementById(`tab-${name}`).classList.add('active');
      btn.classList.add('active');
      if (name === 'history') { loadHistory(); loadMemStats(); }
      if (name === 'knowledge') { loadKnowledge(); loadBenignWhitelist(); loadMcpRegistry(); }
    }

    // ═══════════════════════════════════════════════
    // 系统类型选择
    // ═══════════════════════════════════════════════
    let currentOS = 'linux';  // 'linux' | 'windows'

    function selectOS(os) {
      currentOS = os;
      const btnLinux = document.getElementById('osBtnLinux');
      const btnWindows = document.getElementById('osBtnWindows');
      const hint = document.getElementById('osHint');
      const exLinux = document.getElementById('examplesLinux');
      const exWindows = document.getElementById('examplesWindows');

      btnLinux.className = 'os-btn' + (os === 'linux' ? ' active linux' : '');
      btnWindows.className = 'os-btn' + (os === 'windows' ? ' active windows' : '');

      if (os === 'linux') {
        hint.textContent = '当前：Linux 模式 — AI 使用 bash 语法和 Linux 安全巡检知识';
        exLinux.style.display = '';
        exWindows.style.display = 'none';
      } else {
        hint.textContent = '当前：Windows 模式 — AI 使用 cmd/PowerShell 语法和 Windows 安全巡检知识';
        exLinux.style.display = 'none';
        exWindows.style.display = '';
      }
      renderCustomTags();
    }

    // ═══════════════════════════════════════════════
    // 自定义快捷指令
    // ═══════════════════════════════════════════════
    function loadCustomTags() {
      try {
        const raw = localStorage.getItem(CUSTOM_TAGS_KEY);
        if (raw) customTags = JSON.parse(raw);
        if (!customTags.linux) customTags.linux = [];
        if (!customTags.windows) customTags.windows = [];
      } catch (e) { customTags = { linux: [], windows: [] }; }
    }

    function saveCustomTags() {
      localStorage.setItem(CUSTOM_TAGS_KEY, JSON.stringify(customTags));
    }

    function renderCustomTags() {
      const container = document.getElementById('customTags');
      const list = customTags[currentOS] || [];
      if (!list.length) {
        container.innerHTML = '<span style="font-size:11px;color:var(--muted);font-style:italic">暂无自定义指令，在下方输入添加</span>';
        return;
      }
      container.innerHTML = list.map((item, idx) => `
    <span class="tag custom-tag" data-task="${btoa(unescape(encodeURIComponent(item.task)))}">
      ${esc(item.label || item.task.substring(0, 14) + (item.task.length > 14 ? '…' : ''))}
      <button class="tag-del" data-idx="${idx}" title="删除此指令">✕</button>
    </span>`).join('');
    }

    function addCustomTag() {
      const taskInput = document.getElementById('newTagInput');
      const labelInput = document.getElementById('newTagLabel');
      const task = taskInput.value.trim();
      const label = labelInput.value.trim();
      if (!task) { toast('请输入指令内容', 'fail'); taskInput.focus(); return; }

      if (!customTags[currentOS]) customTags[currentOS] = [];
      // 防重复
      if (customTags[currentOS].some(t => t.task === task)) {
        toast('该指令已存在', 'fail'); return;
      }
      customTags[currentOS].push({ label: label || task.substring(0, 14) + (task.length > 14 ? '…' : ''), task });
      saveCustomTags();
      renderCustomTags();
      taskInput.value = '';
      labelInput.value = '';
      toast('已添加到自定义快捷指令');
    }

    function deleteCustomTag(e, idx) {
      e.stopPropagation();
      customTags[currentOS].splice(idx, 1);
      saveCustomTags();
      renderCustomTags();
      toast('已删除');
    }

    // ═══════════════════════════════════════════════
    // 任务执行
    // ═══════════════════════════════════════════════
    function setTask(text) {
      const input = document.getElementById('taskInput');
      input.value = text;
      input.focus();
      autoResize(input);
    }

    function handleTaskInputKey(event) {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        runTask();
      }
    }

    function handleCustomTagKey(event) {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        addCustomTag();
      }
    }

    function setStatus(type, text) {
      const bar = document.getElementById('statusBar');
      const spinner = document.getElementById('statusSpinner');
      bar.className = `status-bar show ${type}`;
      document.getElementById('statusText').textContent = text;
      spinner.style.display = type === 'running' ? 'block' : 'none';
    }

    function runTask() {
      const task = document.getElementById('taskInput').value.trim();
      if (!task) { toast('请输入任务描述', 'fail'); return; }

      const osLabel = currentOS === 'windows' ? '🪟 Windows' : '🐧 Linux';
      stepCount = 0; currentTaskId = null;
      document.getElementById('stepsContainer').innerHTML = '';
      document.getElementById('timeline').style.display = 'none';
      document.getElementById('finalCard').classList.remove('show');
      document.getElementById('stepCounter').textContent = '';
      document.getElementById('runBtn').disabled = true;
      document.getElementById('runBtn').style.display = 'none';
      document.getElementById('stopBtn').style.display = 'inline-flex';
      document.getElementById('stopBtn').disabled = false;
      document.getElementById('stopBtn').textContent = '⏹ 停止';
      setStatus('running', `[${osLabel}] 正在执行：${task.substring(0, 40)}${task.length > 40 ? '...' : ''}`);

      if (currentEventSource) currentEventSource.close();

      const es = new EventSource(`/task/stream?task=${encodeURIComponent(task)}&os_type=${currentOS}`);
      currentEventSource = es;

      es.onmessage = e => handleEvent(JSON.parse(e.data));
      es.onerror = () => {
        es.close();
        setStatus('error', '连接断开，请检查服务是否正在运行');
        resetTaskBtns();
      };
    }

    async function stopTask() {
      // 1. 立即关闭 SSE 连接 —— 这会触发后端的 CancelledError，后端自动 set stop_event
      if (currentEventSource) {
        currentEventSource.close();
        currentEventSource = null;
      }

      // 2. 立即更新 UI，不等待后端响应
      resetTaskBtns();
      setStatus('error', '任务已停止');

      // 3. 异步发送 stop 请求兜底（非阻塞，不管成功失败）
      if (currentTaskId) {
        const tid = currentTaskId;
        currentTaskId = null;
        fetch(`/task/stop/${tid}`, { method: 'POST' }).catch(() => { });
      }
    }

    function resetTaskBtns() {
      document.getElementById('runBtn').disabled = false;
      document.getElementById('runBtn').style.display = 'inline-flex';
      document.getElementById('stopBtn').style.display = 'none';
      document.getElementById('stopBtn').disabled = false;
      document.getElementById('stopBtn').textContent = '⏹ 停止';
    }

    function handleEvent(data) {
      const { event } = data;
      if (event === 'start') {
        currentTaskId = data.task_id;
        document.getElementById('timeline').style.display = 'block';
      }
      if (event === 'thinking') {
        stepCount++;
        document.getElementById('stepCounter').textContent = `第 ${stepCount} 步`;
        addStep(data, 'running');
      }
      if (event === 'step_result') updateStep(data);
      if (event === 'stopped') {
        document.getElementById('finalCard').classList.add('show');
        document.getElementById('finalCard').querySelector('h3').innerHTML =
          '⏹ 任务已停止 <button class="copy-btn" onclick="copyFinal()">复制结果</button>';
        document.getElementById('finalCard').style.borderColor = 'var(--yellow)';
        setFinalAnswer(`任务已被手动停止（共完成 ${stepCount} 步）`);
        setStatus('error', `⏹ 已停止，共 ${stepCount} 步`);
        resetTaskBtns();
        currentEventSource && currentEventSource.close();
      }
      if (event === 'done') {
        document.getElementById('finalCard').classList.add('show');
        document.getElementById('finalCard').querySelector('h3').innerHTML =
          '✅ 任务完成 <button class="copy-btn" onclick="copyFinal()">复制结果</button>';
        document.getElementById('finalCard').style.borderColor = '';
        setFinalAnswer(data.final_answer || '任务已完成');
        setStatus('done', `✅ 完成，共 ${stepCount} 步`);
        resetTaskBtns();
        currentEventSource.close();
      }
      if (event === 'error') {
        setStatus('error', `错误：${data.message}`);
        resetTaskBtns();
        currentEventSource.close();
      }
    }

    function addStep(data, state) {
      const container = document.getElementById('stepsContainer');
      const card = document.createElement('div');
      card.className = 'step-card expanded';
      card.id = `step-${data.step}`;
      card.innerHTML = `
    <div class="step-header" onclick="this.parentElement.classList.toggle('expanded')">
      <div class="step-num running" id="sn-${data.step}">…</div>
      <span class="step-tool">${esc(data.tool)}</span>
      <span class="step-cmd">${esc(data.command || '')}</span>
      <span class="step-chevron">▶</span>
    </div>
    <div class="step-body">
      <div class="label-sm yellow">AI 思考</div>
      <div class="thought-box">${esc(data.thought || '')}</div>
      <div class="label-sm">执行结果</div>
      <div class="output-box" id="so-${data.step}">等待执行...</div>
    </div>`;
      container.appendChild(card);
      card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function updateStep(data) {
      const sn = document.getElementById(`sn-${data.step}`);
      const so = document.getElementById(`so-${data.step}`);
      const stepStatus = data.status || (data.success ? 'ok' : 'error');
      let badgeClass = 'ok';
      let badgeText = '✓';
      if (stepStatus === 'partial') {
        badgeClass = 'partial';
        badgeText = '!';
      } else if (stepStatus === 'error') {
        badgeClass = 'fail';
        badgeText = '✗';
      }
      if (sn) { sn.className = `step-num ${badgeClass}`; sn.textContent = badgeText; }
      if (so) {
        const note = data.note ? `\n\n[状态说明] ${data.note}` : '';
        so.textContent = (data.result || '(无输出)') + note;
      }
      document.querySelectorAll('.step-card').forEach((c, i, arr) => {
        if (i < arr.length - 1) c.classList.remove('expanded');
      });
    }

    function copyFinal() {
      copyText(finalAnswerRaw || document.getElementById('finalAnswer').textContent);
    }

    function openChatAssist() {
      document.querySelectorAll('.tab-btn')[1].click();
    }

    // ═══════════════════════════════════════════════
    // AI 对话助手
    // ═══════════════════════════════════════════════
    function autoResize(el) {
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 120) + 'px';
    }

    function handleChatKey(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChat();
      }
    }

    function setChatMode(mode, btn) {
      chatMode = mode;
      document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const desc = document.getElementById('modeDesc');
      if (mode === 'refine') {
        desc.textContent = '帮你把模糊需求改成带检查范围、证据面和输出要求的可执行任务指令';
      } else {
        desc.textContent = '自由提问，适合咨询命令、安全排查思路、日志分析和运维问题';
      }
    }

    function sendQuickMsg(msg) {
      document.getElementById('chatInput').value = msg;
      sendChat();
    }

    function clearChat() {
      chatHistory = [];
      const container = document.getElementById('chatMessages');
      container.innerHTML = `<div class="msg assistant">
    👋 对话已清空。告诉我你想做什么？
  </div>`;
    }

    /**
     * 从 AI 回复中剥离 <think>...</think> 思维链内容。
     * MiniMax-M1 / DeepSeek-R1 等推理模型会输出这些标签，不应展示给用户。
     */
    function stripThinkTags(text) {
      if (!text) return '';
      // 移除所有 think 标签及其内容（支持多种变体）
      text = text.replace(/<think>[\s\S]*?<\/think>/gi, '');
      text = text.replace(/<think>[\s\S]*?<\/think>/gi, '');
      text = text.replace(/<think>[\s\S]*/i, '');  // 防止只有开始标签没有结束标签
      // 移除多余的空行
      text = text.replace(/\n\s*\n\s*\n/g, '\n\n');
      return text.trim();
    }

    function appendChatMsg(role, content, extra = '') {
      const container = document.getElementById('chatMessages');
      const div = document.createElement('div');
      div.className = `msg ${role}`;

      if (role === 'assistant') {
        // 先剥离思维链标签
        content = stripThinkTags(content);

        // 最稳健的方案：只匹配 "推荐任务指令" 后面的第一个代码块
        // 忽略中间的任意内容，只找第一个 ```...```
        const recMatch = content.match(/(?:推荐任务指令 | 推荐任务)[：:\s]*[\s\S]*?```([^]*?)```/i);

        if (recMatch && recMatch[1]) {
          // 提取代码块内容，去掉 Markdown 标记和多余空行
          let task = recMatch[1].trim();
          // 去掉可能的语言标识（如 ```bash）
          task = task.replace(/^bash\s*\n/, '\n').replace(/^shell\s*\n/, '\n').trim();

          if (task) {
            const before = content.substring(0, recMatch.index);
            // 使用 data-* 属性存储任务文本，避免 JSON.stringify 在 onclick 中的问题
            // 注意：不能直接在内联 onclick 中使用 JSON.stringify(task)，因为会破坏 HTML 结构
            div.innerHTML = esc(before).replace(/\n/g, '<br>') +
              `<div class="recommend-box">
            <div class="rec-title">✅ 推荐任务指令</div>
            <code>${esc(task)}</code>
            <button class="use-btn" data-task="${btoa(unescape(encodeURIComponent(task)))}">📋 复制指令</button>
          </div>`;
          } else {
            div.textContent = content;
          }
        } else {
          div.textContent = content;
        }
      } else {
        div.textContent = content;
      }
      container.appendChild(div);
      container.scrollTop = container.scrollHeight;
      return div;
    }

    function useRecommendedTask(task) {
      // 1. 切换到任务执行标签页
      const execBtn = document.querySelectorAll('.tab-btn')[0];
      if (execBtn) execBtn.click();

      // 2. 自动填入任务内容
      setTimeout(() => {
        const taskInput = document.getElementById('taskInput');
        if (taskInput) {
          taskInput.value = task;
          taskInput.focus();
          taskInput.style.backgroundColor = 'rgba(63, 185, 80, 0.2)';
          setTimeout(() => {
            taskInput.style.backgroundColor = '';
          }, 1500);
        }

        // 3. 显示提示
        toast('已填入任务指令，点击"执行"按钮开始', 'ok', 4000);
      }, 300);
    }

    async function sendChat() {
      const input = document.getElementById('chatInput');
      const msg = input.value.trim();
      if (!msg || isChatLoading) return;

      input.value = '';
      input.style.height = 'auto';

      appendChatMsg('user', msg);
      chatHistory.push({ role: 'user', content: msg });

      // 显示打字指示
      const container = document.getElementById('chatMessages');
      const typingDiv = document.createElement('div');
      typingDiv.className = 'msg-typing';
      typingDiv.textContent = 'AI 正在思考...';
      container.appendChild(typingDiv);
      container.scrollTop = container.scrollHeight;
      isChatLoading = true;

      try {
        // 用流式接口实时显示
        const resp = await fetch('/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: msg,
            history: chatHistory.slice(-10),  // 只传最近10轮
            mode: chatMode,
            os_type: currentOS,  // 传递当前选择的 OS 类型
          })
        });

        typingDiv.remove();

        const aiDiv = document.createElement('div');
        aiDiv.className = 'msg assistant';
        aiDiv.textContent = '';
        container.appendChild(aiDiv);

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let fullText = '';

        // 是否正在 think 标签内（流式输出时逐步过滤）
        let inThinkTag = false;
        let thinkBuf = '';   // 缓冲未闭合的 think 片段

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value);
          const lines = chunk.split('\n');
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6).trim();
              if (data === '[DONE]') break;
              try {
                const obj = JSON.parse(data);
                if (obj.token) {
                  fullText += obj.token;
                  // 实时渲染：过滤 <think> 标签，不显示推理内容
                  const displayText = stripThinkTags(fullText);
                  aiDiv.textContent = displayText || '▌';
                  container.scrollTop = container.scrollHeight;
                }
                if (obj.error) {
                  aiDiv.textContent = '❌ 错误：' + obj.error;
                }
              } catch (e) { }
            }
          }
        }

        // 流结束后，重新渲染（解析推荐任务框，已包含 think 过滤）
        aiDiv.remove();
        appendChatMsg('assistant', fullText);
        chatHistory.push({ role: 'assistant', content: fullText });

      } catch (e) {
        typingDiv.remove();
        appendChatMsg('assistant', '❌ 请求失败：' + e.message);
      }

      isChatLoading = false;
    }

    // ═══════════════════════════════════════════════
    // 工具知识库 - 导入/导出
    // ═══════════════════════════════════════════════
    async function exportKnowledge() {
      try {
        console.log('开始导出...');
        const resp = await fetch('/tool-knowledge/export');
        console.log('响应状态:', resp.status);
        if (!resp.ok) {
          const err = await resp.text();
          console.error('导出失败:', err);
          throw new Error('HTTP ' + resp.status);
        }
        const blob = await resp.blob();
        console.log('Blob大小:', blob.size);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `tool_knowledge_${new Date().toISOString().slice(0, 10)}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        toast('知识库已导出');
      } catch (e) {
        console.error('导出错误:', e);
        toast('导出失败: ' + e.message, 'fail');
      }
    }

    async function importKnowledge(input) {
      const file = input.files[0];
      if (!file) return;
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        const resp = await fetch('/tool-knowledge/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ data: data, mode: 'merge' })
        });
        const result = await resp.json();
        if (result.success) {
          toast(`导入成功: ${result.imported_count} 个工具`);
          // 延迟刷新确保数据已写入
          setTimeout(() => {
            loadKnowledge();
            // 如果有导入的工具，自动选中第一个
            if (data.tools && Object.keys(data.tools).length > 0) {
              const firstTool = Object.keys(data.tools)[0];
              selectTool(firstTool);
            }
          }, 300);
        } else {
          toast('导入失败: ' + result.message, 'fail');
        }
      } catch (e) {
        toast('导入失败: ' + e.message, 'fail');
      }
      input.value = '';
    }

    async function exportMcpRegistry() {
      try {
        const resp = await fetch('/mcp/registry/export');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `tool_registry_${new Date().toISOString().slice(0, 10)}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        toast('技能包已导出');
      } catch (e) {
        toast('技能包导出失败: ' + e.message, 'fail');
      }
    }

    async function importMcpRegistry(input) {
      const file = input.files[0];
      if (!file) return;
      try {
        const text = await file.text();
        const parsed = JSON.parse(text);
        const payload = {
          mode: parsed.mode || 'merge',
          data: parsed.data && typeof parsed.data === 'object' ? parsed.data : parsed
        };
        const resp = await fetch('/mcp/registry/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const result = await resp.json();
        if (!resp.ok) {
          throw new Error(result.detail || result.message || ('HTTP ' + resp.status));
        }
        toast(`技能包导入成功: ${result.imported_count} 个工具`);
        loadMcpRegistry();
      } catch (e) {
        toast('技能包导入失败: ' + e.message + '。请确认文件内容是合法 JSON，并且包含 tool+capabilities 或 tools 字段', 'fail');
      }
      input.value = '';
    }

    // ═══════════════════════════════════════════════
    // 工具知识库
    // ═══════════════════════════════════════════════
    async function loadKnowledge() {
      try {
        const r = await fetch('/tool-knowledge');
        const d = await r.json();
        knowledgeData = d.items || [];
        renderKnowledgeList();
        document.getElementById('knowledgeCount').textContent = `${d.total} 个`;
      } catch (e) {
        document.getElementById('knowledgeItems').innerHTML = '<div class="empty" style="color:var(--red)">加载失败</div>';
      }
    }

    function splitLines(text) {
      return String(text || '')
        .split(/\r?\n/)
        .map(s => s.trim())
        .filter(Boolean);
    }

    async function loadBenignWhitelist() {
      try {
        const r = await fetch('/benign-whitelist');
        const d = await r.json();
        benignWhitelistData = d;
        document.getElementById('benignProcesses').value = (d.processes || []).join('\n');
        document.getElementById('benignPaths').value = (d.paths || []).join('\n');
        document.getElementById('benignNetworkNote').value = d.network_note || '';
      } catch (e) {
        toast('良性白名单加载失败', 'fail');
      }
    }

    async function loadMcpRegistry() {
      try {
        const r = await fetch('/mcp/registry');
        const d = await r.json();
        mcpRegistryData = d.items || [];
        renderMcpRegistry();
        const countEl = document.getElementById('mcpCount');
        if (countEl) countEl.textContent = `${d.total || mcpRegistryData.length} 个`;
      } catch (e) {
        const container = document.getElementById('mcpRegistryList');
        if (container) {
          container.innerHTML = '<div class="empty" style="color:var(--red)">技能列表加载失败</div>';
        }
      }
    }

    async function saveBenignWhitelist() {
      const body = {
        processes: splitLines(document.getElementById('benignProcesses').value),
        paths: splitLines(document.getElementById('benignPaths').value),
        network_note: document.getElementById('benignNetworkNote').value.trim(),
      };

      try {
        const r = await fetch('/benign-whitelist', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const d = await r.json();
        if (!r.ok) {
          toast(d.detail || '保存失败', 'fail');
          return;
        }
        benignWhitelistData = d;
        toast(d.message || '良性白名单已保存');
        closeWhitelist();
      } catch (e) {
        toast('保存失败: ' + e.message, 'fail');
      }
    }

    async function openWhitelist() {
      await loadBenignWhitelist();
      document.getElementById('whitelistOverlay').classList.add('show');
    }

    function closeWhitelist(e) {
      if (!e || e.target === document.getElementById('whitelistOverlay')) {
        document.getElementById('whitelistOverlay').classList.remove('show');
      }
    }

    function renderKnowledgeList() {
      const container = document.getElementById('knowledgeItems');
      if (!knowledgeData.length) {
        container.innerHTML = '<div class="empty">暂无知识记录<br><small>执行任务时 AI 会自动学习工具用法</small></div>';
        return;
      }
      container.innerHTML = knowledgeData.map(item => {
        const errCount = (item.errors || []).length;
        const hintCount = (item.usage_hints || []).length;
        return `<div class="knowledge-item ${item.tool === selectedToolName ? 'active' : ''}" onclick="selectTool('${esc(item.tool)}')">
      <div class="ki-name">${esc(item.tool)}</div>
      <div class="ki-meta">
        ${errCount ? `<span class="ki-badge errors">✗ ${errCount}个错误</span>` : ''}
        ${hintCount ? `<span class="ki-badge hints">✓ ${hintCount}条用法</span>` : ''}
        ${item.help_summary ? '<span style="color:var(--muted)">📄帮助文档</span>' : ''}
      </div>
    </div>`;
      }).join('');
    }

    function renderMcpRegistry() {
      const container = document.getElementById('mcpRegistryList');
      if (!container) return;
      if (!mcpRegistryData.length) {
        container.innerHTML = '<div class="empty">暂无技能包<br><small>点击上方「导入技能包」导入</small></div>';
        return;
      }

      container.innerHTML = mcpRegistryData.map(item => {
        const capabilities = item.capabilities || [];
        const toolPath = item.tool_path || '';
        return `
          <div class="mcp-card">
            <div class="mcp-name">${esc(item.tool || '')}</div>
            <div class="mcp-meta">
              <div>${esc(item.summary || '未填写工具摘要')}</div>
              <div>能力数量：${capabilities.length}</div>
              ${toolPath ? `<div>路径：${esc(toolPath)}</div>` : ''}
            </div>
            <div class="mcp-cap-list">
              ${capabilities.slice(0, 8).map(cap => `<span class="mcp-cap-tag">${esc(cap.name || '')}</span>`).join('')}
              ${capabilities.length > 8 ? `<span class="mcp-cap-tag">+${capabilities.length - 8}</span>` : ''}
            </div>
            <div class="mcp-actions">
              <button class="btn btn-outline btn-xs" style="color:var(--red);border-color:var(--red)" onclick="deleteMcpTool('${esc(item.tool || '')}')">卸载</button>
            </div>
          </div>
        `;
      }).join('');
    }

    async function deleteMcpTool(toolName) {
      if (!toolName) return;
      const ok = confirm(`确定卸载技能 ${toolName} 吗？`);
      if (!ok) return;
      try {
        const resp = await fetch(`/mcp/registry/${encodeURIComponent(toolName)}`, {
          method: 'DELETE'
        });
        const result = await resp.json();
        if (!resp.ok) {
          throw new Error(result.detail || ('HTTP ' + resp.status));
        }
        toast(result.message || `已卸载技能 ${toolName}`);
        loadMcpRegistry();
      } catch (e) {
        toast('卸载技能失败: ' + e.message, 'fail');
      }
    }

    function selectTool(toolName) {
      selectedToolName = toolName;
      renderKnowledgeList();
      const rec = knowledgeData.find(i => i.tool === toolName);
      if (!rec) { renderKnowledgeDetail(null); return; }
      renderKnowledgeDetail(rec);
    }

    function renderKnowledgeDetail(rec) {
      const container = document.getElementById('knowledgeDetail');
      if (!rec) {
        container.innerHTML = '<div class="no-selection"><span style="font-size:20px;font-weight:700">知识</span><span>点击左侧工具查看详情</span></div>';
        return;
      }

      const hints = rec.usage_hints || [];
      const errors = rec.errors || [];
      const updatedAt = rec.updated_at ? new Date(rec.updated_at * 1000).toLocaleString('zh-CN') : '未知';
      const isAiExplored = rec.source === 'ai_explore';
      const toolPath = rec.tool_path || '';

      // 顶部操作栏
      let html = `
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:20px;flex-wrap:wrap">
      <span style="font-size:20px;font-weight:700">${esc(rec.tool)}</span>
      ${toolPath ? `<code style="background:var(--bg);padding:4px 8px;border-radius:4px;font-size:12px">${esc(toolPath)}</code>` : ''}
    </div>
  `;

      // 工具简介（如果有）
      if (rec.summary) {
        html += `<div style="margin-bottom:20px;padding:12px;background:var(--bg);border-radius:8px;border-left:3px solid var(--accent)">
      <div style="font-size:12px;color:var(--muted);margin-bottom:4px">工具简介</div>
      <div style="font-size:14px;line-height:1.6">${esc(rec.summary)}</div>
    </div>`;
      }

      // 正确用法（核心）
      if (hints.length) {
        html += `<div style="margin-bottom:20px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
        <span style="font-size:14px;font-weight:600">✅ 可用命令</span>
        <span style="font-size:11px;color:var(--muted)">${hints.length}条</span>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px">
        ${hints.map(h => `
          <div style="background:var(--bg);padding:10px 14px;border-radius:6px;font-family:monospace;font-size:13px;line-height:1.5">
            ${esc(h)}
          </div>
        `).join('')}
      </div>
    </div>`;
      }

      // 帮助信息（如果有）
      if (rec.help_summary && rec.help_summary !== rec.summary) {
        html += `<div style="margin-bottom:20px">
      <div style="font-size:12px;font-weight:600;color:var(--muted);margin-bottom:8px">📖 帮助信息</div>
      <div style="background:var(--bg);padding:12px;border-radius:6px;font-size:12px;line-height:1.6;color:var(--text);white-space:pre-wrap;max-height:200px;overflow-y:auto">${esc(rec.help_summary)}</div>
    </div>`;
      }

      // 错误记录（如果有）
      if (errors.length) {
        html += `<div style="margin-bottom:20px">
      <div style="font-size:12px;font-weight:600;color:var(--red);margin-bottom:8px">⚠️ 已知错误 (${errors.length})</div>
      ${errors.slice(-3).reverse().map(e => `
        <div style="background:var(--bg);padding:10px;border-radius:6px;margin-bottom:8px;font-size:12px">
          <div style="color:var(--red)">✗ ${esc(e.failed_command || '')}</div>
          ${e.error_output ? `<div style="color:var(--muted);margin-top:4px">${esc(e.error_output.substring(0, 100))}</div>` : ''}
          ${e.fixed_command ? `<div style="color:var(--green);margin-top:4px">✓ 正确: ${esc(e.fixed_command)}</div>` : ''}
        </div>
      `).join('')}
    </div>`;
      }

      // 底部操作
      html += `
    <div style="margin-top:20px;padding-top:16px;border-top:1px solid var(--border);display:flex;gap:10px;flex-wrap:wrap">
      <button class="btn btn-sm" style="background:var(--purple);color:#fff" onclick="relearn('${esc(rec.tool)}','${esc(toolPath)}')">重新学习</button>
      <button class="btn btn-outline btn-sm" onclick="showEditTool('${esc(rec.tool)}')">编辑</button>
      <button class="btn btn-outline btn-sm" style="color:var(--red);border-color:var(--red)" onclick="deleteToolKnowledge('${esc(rec.tool)}')">删除</button>
      <span style="font-size:11px;color:var(--muted);margin-left:auto;align-self:center">更新于 ${updatedAt}</span>
    </div>
  `;

      container.innerHTML = html;
    }

    // 清除参考资料
    async function clearRef(toolName) {
      if (!confirm(`确定要清除工具 "${toolName}" 的参考资料吗？`)) return;
      try {
        const resp = await fetch(`/tool-knowledge/reference/${encodeURIComponent(toolName)}`, { method: 'DELETE' });
        if (resp.ok) {
          alert('已清除参考资料');
          loadKnowledge(); // 刷新
        } else {
          alert('清除失败');
        }
      } catch (e) {
        alert('错误: ' + e.message);
      }
    }

    function showAddKnowledge() {
      document.getElementById('addKnowledgePanel').style.display = 'block';
      document.getElementById('ak_tool').focus();
    }

    function showEditKnowledge(toolName) {
      document.getElementById('addKnowledgePanel').style.display = 'block';
      document.getElementById('ak_tool').value = toolName;
      document.getElementById('ak_tool').scrollIntoView({ behavior: 'smooth' });
    }

    // 编辑工具（修改路径、简介等）
    function showEditTool(toolName) {
      const rec = knowledgeData.find(i => i.tool === toolName);
      if (!rec) return;

      // 创建编辑弹窗
      const modal = document.createElement('div');
      modal.id = 'editToolModal';
      modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:1000';
      modal.innerHTML = `
    <div style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:24px;width:90%;max-width:500px;max-height:80vh;overflow-y:auto">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
        <span style="font-size:16px;font-weight:600">✏ 编辑工具</span>
        <button onclick="closeEditToolModal()" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:20px">×</button>
      </div>
      <div style="display:flex;flex-direction:column;gap:12px">
        <div>
          <label style="font-size:12px;color:var(--muted);margin-bottom:4px;display:block">工具名称</label>
          <input type="text" id="editToolName" value="${esc(toolName)}" readonly style="width:100%;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--muted)">
        </div>
        <div>
          <label style="font-size:12px;color:var(--muted);margin-bottom:4px;display:block">工具路径</label>
          <input type="text" id="editToolPath" value="${esc(rec.tool_path || '')}" placeholder="如: /usr/bin/nmap" style="width:100%;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text)">
        </div>
        <div>
          <label style="font-size:12px;color:var(--muted);margin-bottom:4px;display:block">工具简介</label>
          <textarea id="editToolSummary" rows="3" placeholder="简短描述工具功能..." style="width:100%;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);resize:vertical">${esc(rec.summary || '')}</textarea>
        </div>
        <div>
          <label style="font-size:12px;color:var(--muted);margin-bottom:4px;display:block">帮助信息摘要</label>
          <textarea id="editToolHelp" rows="4" placeholder="帮助文档摘要..." style="width:100%;padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);resize:vertical">${esc(rec.help_summary || '')}</textarea>
        </div>
      </div>
      <div style="margin-top:20px;display:flex;gap:10px;justify-content:flex-end">
        <button class="btn btn-outline" onclick="closeEditToolModal()">取消</button>
        <button class="btn" style="background:var(--purple);color:#000" onclick="saveEditTool()">保存</button>
      </div>
    </div>
  `;
      document.body.appendChild(modal);
    }

    function closeEditToolModal() {
      const modal = document.getElementById('editToolModal');
      if (modal) modal.remove();
    }

    async function saveEditTool() {
      const toolName = document.getElementById('editToolName').value.trim();
      const toolPath = document.getElementById('editToolPath').value.trim();
      const summary = document.getElementById('editToolSummary').value.trim();
      const helpSummary = document.getElementById('editToolHelp').value.trim();

      if (!toolName) return;

      try {
        // 调用更新接口
        const r = await fetch('/tool-knowledge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            tool_name: toolName,
            usage_hint: '',  // 不修改用法
            help_text: helpSummary,
            tool_path: toolPath,
            summary: summary
          })
        });

        // 更新本地数据
        const rec = knowledgeData.find(i => i.tool === toolName);
        if (rec) {
          rec.tool_path = toolPath;
          rec.summary = summary;
          rec.help_summary = helpSummary;
          rec.updated_at = Date.now() / 1000;
        }

        closeEditToolModal();
        renderKnowledgeDetail(rec);
        renderKnowledgeList();
        toast('已保存修改');
      } catch (e) {
        toast('保存失败: ' + e.message, 'fail');
      }
    }

    function hideAddKnowledge() {
      document.getElementById('addKnowledgePanel').style.display = 'none';
      ['ak_tool', 'ak_hint', 'ak_help', 'ak_failed', 'ak_fixed', 'ak_error'].forEach(id => {
        document.getElementById(id).value = '';
      });
    }

    async function submitKnowledge() {
      const toolName = document.getElementById('ak_tool').value.trim();
      if (!toolName) { toast('请填写工具名', 'fail'); return; }

      const body = {
        tool_name: toolName,
        usage_hint: document.getElementById('ak_hint').value.trim(),
        help_text: document.getElementById('ak_help').value.trim(),
        failed_command: document.getElementById('ak_failed').value.trim(),
        fixed_command: document.getElementById('ak_fixed').value.trim(),
        error_output: document.getElementById('ak_error').value.trim(),
      };

      try {
        const r = await fetch('/tool-knowledge', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });
        const d = await r.json();
        toast(d.message || '已保存');
        hideAddKnowledge();
        loadKnowledge();
      } catch (e) { toast('保存失败: ' + e.message, 'fail'); }
    }

    async function deleteToolKnowledge(toolName) {
      showConfirm('删除工具知识', `确定删除工具「${toolName}」的所有知识记录吗？`, async () => {
        try {
          await fetch(`/tool-knowledge/${encodeURIComponent(toolName)}`, { method: 'DELETE' });
          toast('已删除');
          selectedToolName = null;
          loadKnowledge();
          document.getElementById('knowledgeDetail').innerHTML = '<div class="no-selection"><span style="font-size:20px;font-weight:700">知识</span><span>选择左侧工具查看详情</span></div>';
        } catch (e) { toast('删除失败', 'fail'); }
      });
    }

    // ═══════════════════════════════════════════════
    // AI 自学功能
    // ═══════════════════════════════════════════════
    let learnEventSource = null;
    let currentLearnStepNo = 0;

    function toggleLearnPanel() {
      const panel = document.getElementById('learnPanel');
      const isVisible = panel.style.display !== 'none';
      panel.style.display = isVisible ? 'none' : 'block';
      if (!isVisible) document.getElementById('learnToolName').focus();
    }


    // 重新学习（带参考资料）
    async function relearnWithRef(toolName, toolPath) {
      // 先展开自学面板
      document.getElementById('learnPanel').style.display = 'block';
      document.getElementById('learnToolName').value = toolName;
      if (toolPath) document.getElementById('learnToolPath').value = toolPath;
      document.getElementById('learnPanel').scrollIntoView({ behavior: 'smooth' });
      document.getElementById('learnToolPath').focus();

      // 检查是否有参考资料
      try {
        const resp = await fetch(`/tool-knowledge/reference/${encodeURIComponent(toolName)}`);
        if (resp.ok) {
          const data = await resp.json();
          if (confirm(`该工具有已导入的参考资料，是否在自学时使用？\n\n点击"确定"使用资料学习，点击"取消"重新导入新资料`)) {
            // 有资料，直接开始学习即可，AI会自动加载
            return;
          }
        }
      } catch (e) {
        // 没有参考资料，正常进行
      }
    }

    function relearn(toolName, toolPath) {
      // 点「重新探索」：自动填入信息并展开面板
      document.getElementById('learnPanel').style.display = 'block';
      document.getElementById('learnToolName').value = toolName;
      if (toolPath) document.getElementById('learnToolPath').value = toolPath;
      document.getElementById('learnPanel').scrollIntoView({ behavior: 'smooth' });
      document.getElementById('learnToolPath').focus();
    }

    function setLearnStatus(type, text) {
      const el = document.getElementById('learnStatus');
      el.className = `learn-status ${type}`;
      const spinner = type === 'running' ? '<div class="spinner" style="width:12px;height:12px;flex-shrink:0"></div>' : '';
      el.innerHTML = `${spinner}<span>${text}</span>`;
    }

    function addLearnStep(step, thought, command) {
      currentLearnStepNo = step;
      const container = document.getElementById('learnSteps');
      const div = document.createElement('div');
      div.className = 'learn-step';
      div.id = `lstep-${step}`;
      div.innerHTML = `
    <div class="learn-step-header">
      <div class="learn-step-num running" id="lsn-${step}">${step}</div>
      <span class="learn-step-cmd">${esc(command || '思考中...')}</span>
    </div>
    ${thought ? `<div class="learn-step-thought">${esc(thought)}</div>` : ''}
    <div class="learn-step-output" id="lso-${step}" style="display:none"></div>
  `;
      container.appendChild(div);
      container.scrollTop = container.scrollHeight;
    }

    function updateLearnStep(step, output, success) {
      const num = document.getElementById(`lsn-${step}`);
      const out = document.getElementById(`lso-${step}`);
      if (num) {
        num.className = `learn-step-num ${success ? 'ok' : 'fail'}`;
        num.textContent = success ? '✓' : '✗';
      }
      if (out && output) {
        out.style.display = 'block';
        out.textContent = output;
      }
    }

    async function startLearn() {
      const toolName = document.getElementById('learnToolName').value.trim();
      const toolPath = document.getElementById('learnToolPath').value.trim();
      const refContent = document.getElementById('learnRefContent').value.trim();

      if (!toolName) { toast('请输入工具名', 'fail'); return; }
      if (!toolPath) { toast('请输入工具路径（在目标机器上的路径）', 'fail'); return; }

      // 重置进度区
      document.getElementById('learnProgress').classList.add('show');
      document.getElementById('learnSteps').innerHTML = '';
      document.getElementById('learnResult').style.display = 'none';
      currentLearnStepNo = 0;
      document.getElementById('learnBtn').disabled = true;
      const refHint = refContent ? '（使用参考资料验证）' : '（自行探索）';
      setLearnStatus('running', `AI 正在${refContent ? '验证' : '探索'}工具 "${toolName}" 的用法 ${refHint}...`);

      if (learnEventSource) learnEventSource.close();

      try {
        // 如果填写了参考资料，先导入
        if (refContent) {
          await fetch('/tool-knowledge/reference', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tool_name: toolName, raw_content: refContent })
          });
        }

        const resp = await fetch('/tool-knowledge/learn', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            tool_name: toolName,
            tool_path: toolPath,
            web_reference: refContent || null
          })
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split('\n');
          buf = lines.pop();  // 保留不完整的行
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const ev = JSON.parse(line.slice(6));
                handleLearnEvent(ev, toolName);
              } catch (e) { }
            }
          }
        }
      } catch (e) {
        setLearnStatus('error', '连接失败：' + e.message);
        document.getElementById('learnBtn').disabled = false;
      }
    }

    function handleLearnEvent(ev, toolName) {
      const { event } = ev;

      if (event === 'start') {
        setLearnStatus('running', `🔍 开始探索 "${toolName}"...`);
      }

      if (event === 'thinking') {
        addLearnStep(ev.step, ev.thought, ev.command);
        setLearnStatus('running', `第 ${ev.step} 步：${ev.command ? ev.command.substring(0, 40) : '思考中'}...`);
      }

      if (event === 'step_result') {
        updateLearnStep(ev.step, ev.output, ev.success);
      }

      if (event === 'done') {
        setLearnStatus('done', `✅ 学习完成！已总结 ${(ev.usage_hints || []).length} 条用法并存档`);
        document.getElementById('learnBtn').disabled = false;

        // 展示结论
        const resultDiv = document.getElementById('learnResult');
        resultDiv.style.display = 'block';
        document.getElementById('learnSummaryText').textContent = ev.summary || '';
        const hintsEl = document.getElementById('learnHintsList');
        if (ev.usage_hints && ev.usage_hints.length) {
          hintsEl.innerHTML = ev.usage_hints.map(h =>
            `<div class="learn-hint">${esc(h)}</div>`
          ).join('');
        } else {
          hintsEl.innerHTML = '<div style="color:var(--muted);font-size:12px">暂无具体用法条目</div>';
        }

        // 刷新知识库列表，并自动选中该工具
        loadKnowledge().then(() => {
          selectTool(toolName);
        });
        toast(`工具 ${toolName} 自学完成，已存入知识库`, 'ok', 4000);
      }

      if (event === 'error') {
        setLearnStatus('error', `❌ ${ev.message}`);
        document.getElementById('learnBtn').disabled = false;
      }
    }

    // ═══════════════════════════════════════════════
    // 执行历史
    // ═══════════════════════════════════════════════
    async function loadHistory() {
      try {
        const r = await fetch('/history?limit=30');
        const d = await r.json();
        renderHistory(d.sessions || []);
        document.getElementById('historyCount').textContent = `共 ${d.total} 条`;
      } catch (e) {
        document.getElementById('historyContainer').innerHTML = '<div class="empty" style="color:var(--red)">加载失败</div>';
      }
    }

    function renderHistory(sessions) {
      const c = document.getElementById('historyContainer');
      if (!sessions.length) { c.innerHTML = '<div class="empty">暂无执行历史</div>'; return; }
      const rows = sessions.map(s => `
    <tr id="row-${s.task_id}">
      <td style="width:32px"><input type="checkbox" class="history-cb" value="${s.task_id}" onchange="onHistoryCbChange()"/></td>
      <td style="font-family:monospace;font-size:11px;color:var(--muted)">${s.task_id}</td>
      <td><div class="task-txt" title="${esc(s.task)}">${esc(s.task)}</div></td>
      <td><span class="pill ${s.status}">${s.status}</span></td>
      <td style="color:var(--muted)">${s.steps}</td>
      <td style="color:var(--muted)">${s.duration}s</td>
      <td style="color:var(--muted);font-size:12px">${new Date(s.start_time * 1000).toLocaleString('zh-CN')}</td>
      <td>
        <button class="action-del" onclick="confirmDeleteOne('${s.task_id}')">删除</button>
      </td>
    </tr>`).join('');
      c.innerHTML = `<table><thead><tr>
    <th><input type="checkbox" id="selectAllCb" onchange="toggleSelectAll(this)"/></th>
    <th>ID</th><th>任务</th><th>状态</th><th>步骤</th><th>耗时</th><th>时间</th><th>操作</th>
  </tr></thead><tbody>${rows}</tbody></table>`;
    }

    function onHistoryCbChange() {
      const checked = document.querySelectorAll('.history-cb:checked');
      const all = document.querySelectorAll('.history-cb');
      // 更新全选框状态
      const selectAll = document.getElementById('selectAllCb');
      if (selectAll) {
        selectAll.checked = checked.length === all.length && all.length > 0;
        selectAll.indeterminate = checked.length > 0 && checked.length < all.length;
      }
      // 高亮选中行
      all.forEach(cb => {
        const row = document.getElementById('row-' + cb.value);
        if (row) row.classList.toggle('selected-row', cb.checked);
      });
      // 显示/隐藏批量操作栏
      const bar = document.getElementById('batchBar');
      const cnt = document.getElementById('batchCount');
      if (checked.length > 0) { bar.classList.add('show'); cnt.textContent = checked.length; }
      else { bar.classList.remove('show'); }
    }

    function toggleSelectAll(cb) {
      document.querySelectorAll('.history-cb').forEach(el => {
        el.checked = cb.checked;
        const row = document.getElementById('row-' + el.value);
        if (row) row.classList.toggle('selected-row', cb.checked);
      });
      const bar = document.getElementById('batchBar');
      const cnt = document.getElementById('batchCount');
      const checked = document.querySelectorAll('.history-cb:checked');
      if (checked.length > 0) { bar.classList.add('show'); cnt.textContent = checked.length; }
      else { bar.classList.remove('show'); }
    }

    function clearSelection() {
      document.querySelectorAll('.history-cb').forEach(el => { el.checked = false; });
      const selectAll = document.getElementById('selectAllCb');
      if (selectAll) { selectAll.checked = false; selectAll.indeterminate = false; }
      document.querySelectorAll('.selected-row').forEach(r => r.classList.remove('selected-row'));
      document.getElementById('batchBar').classList.remove('show');
    }

    function confirmDeleteSelected() {
      const ids = [...document.querySelectorAll('.history-cb:checked')].map(cb => cb.value);
      if (!ids.length) return;
      showConfirm('批量删除记录', `确定删除选中的 ${ids.length} 条历史记录吗？此操作不可撤销！`, async () => {
        let ok = 0, fail = 0;
        for (const id of ids) {
          try { await fetch(`/memory/${id}`, { method: 'DELETE' }); ok++; }
          catch (e) { fail++; }
        }
        toast(fail ? `已删除 ${ok} 条，${fail} 条失败` : `已删除 ${ok} 条记录`);
        loadHistory(); loadMemStats();
      });
    }

    async function loadMemStats() {
      try {
        const r = await fetch('/memory/stats');
        const d = await r.json();
        const items = [
          { label: '总任务', val: d.total_sessions, color: 'var(--accent)' },
          { label: '已完成', val: d.completed, color: 'var(--green)' },
          { label: '失败/中止', val: d.failed, color: 'var(--red)' },
          { label: '持久化文件', val: d.file_size_kb + 'KB', color: 'var(--muted)' },
        ];
        document.getElementById('memStats').innerHTML = items.map(i => `
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:10px 16px;min-width:100px">
        <div style="font-size:20px;font-weight:700;color:${i.color}">${i.val}</div>
        <div style="font-size:11px;color:var(--muted);margin-top:2px">${i.label}</div>
      </div>`).join('');
      } catch (e) { }
    }

    // ─── 确认清除 ─────────────────────────────────
    function showConfirm(title, msg, cb) {
      document.getElementById('confirmTitle').textContent = title;
      document.getElementById('confirmMsg').textContent = msg;
      document.getElementById('confirmOverlay').classList.add('show');
      document.getElementById('confirmOkBtn').onclick = () => { closeConfirm(); cb(); };
    }
    function closeConfirm() { document.getElementById('confirmOverlay').classList.remove('show'); }

    function confirmClearAll() {
      showConfirm('清除全部记忆', '将删除所有历史任务记录，此操作不可撤销！确定清除吗？', async () => {
        try {
          const r = await fetch('/memory/all', { method: 'DELETE' });
          const d = await r.json();
          toast(`已清除 ${d.cleared} 条历史记忆`);
          loadHistory(); loadMemStats();
        } catch (e) { toast('清除失败', 'fail'); }
      });
    }

    function confirmDeleteOne(taskId) {
      showConfirm('删除记忆', `确定删除任务 [${taskId}] 的记忆吗？`, async () => {
        try {
          await fetch(`/memory/${taskId}`, { method: 'DELETE' });
          toast('已删除');
          loadHistory(); loadMemStats();
        } catch (e) { toast('删除失败', 'fail'); }
      });
    }

    // ═══════════════════════════════════════════════
    // 模型设置
    // ═══════════════════════════════════════════════
    async function openSettings() {
      await loadPresets();
      await loadCurrentConfig();
      document.getElementById('settingsOverlay').classList.add('show');
      document.getElementById('testResult').className = 'test-result';
    }

    function closeSettings(e) {
      if (!e || e.target === document.getElementById('settingsOverlay'))
        document.getElementById('settingsOverlay').classList.remove('show');
    }

    async function loadPresets() {
      try {
        const r = await fetch('/model/presets');
        const d = await r.json();
        MODEL_PRESETS = d.presets || {};
        renderProviderGrid();
        // presets 加载完后重刷模型指示器（确保 provider 名称正确显示）
        await refreshModelIndicator();
      } catch (e) { }
    }

    // 自定义提供商 localStorage 键
    const CUSTOM_PROVIDERS_KEY = 'ai_agent_custom_providers';
    let customProviders = {}; // { key: {name, base_url, model, docs} }

    // ─── 各提供商 API Key 多份缓存（明文存 localStorage，仅本地使用）───────────
    const PROVIDER_KEYS_KEY = 'ai_agent_provider_keys';
    // 结构：{ deepseek: 'sk-xxx', openai: 'sk-xxx', ... }
    let providerKeys = {};

    function loadProviderKeys() {
      try {
        const raw = localStorage.getItem(PROVIDER_KEYS_KEY);
        if (raw) providerKeys = JSON.parse(raw);
      } catch (e) { providerKeys = {}; }
    }

    function saveProviderKeys() {
      localStorage.setItem(PROVIDER_KEYS_KEY, JSON.stringify(providerKeys));
    }

    /** 清除所有提供商的本地缓存 API Key（同时清除服务端保存的 Key） */
    function confirmClearAllKeys() {
      showConfirm(
        '清除全部 API Key',
        '将同时清除：① 浏览器本地缓存的所有 Key ② 服务端 config 文件中保存的 Key。清除后需重新配置才能使用。确定继续吗？',
        async () => {
          // 1. 清除浏览器本地缓存
          providerKeys = {};
          saveProviderKeys();

          // 2. 清除服务端保存的 Key
          try {
            const r = await fetch('/model/config/key', { method: 'DELETE' });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || '服务端清除失败');
          } catch (e) {
            toast('服务端 Key 清除失败：' + e.message, 'fail');
            return;
          }

          // 3. 更新 UI
          document.getElementById('cfgApiKey').value = '';
          document.getElementById('cfgApiKey').placeholder = 'sk-...（请重新填写 API Key）';
          const keyStatus = document.getElementById('cfgKeyStatus');
          if (keyStatus) keyStatus.textContent = '';
          // 顶栏指示器更新
          document.getElementById('modelDot').style.background = 'var(--red)';
          renderProviderGrid();
          toast('已彻底清除全部 API Key，请重新配置', 'ok', 4000);
        }
      );
    }

    /** 某个提供商已缓存的 key，无则返回 '' */
    function getProviderKey(providerKey) {
      return providerKeys[providerKey] || '';
    }

    function loadCustomProviders() {
      try {
        const raw = localStorage.getItem(CUSTOM_PROVIDERS_KEY);
        if (raw) customProviders = JSON.parse(raw);
      } catch (e) { customProviders = {}; }
    }

    function saveCustomProviders() {
      localStorage.setItem(CUSTOM_PROVIDERS_KEY, JSON.stringify(customProviders));
    }

    function getMergedPresets() {
      // 合并内置 + 自定义，自定义覆盖同名 key
      return { ...MODEL_PRESETS, ...customProviders };
    }

    function renderProviderGrid() {
      const grid = document.getElementById('providerGrid');
      const descriptions = {
        deepseek: '性价比极高', qwen: '阿里云通义', wenxin: '百度文心',
        moonshot: 'Kimi', zhipu: '智谱GLM', openai: 'GPT系列', custom: '自定义'
      };
      const all = getMergedPresets();
      grid.innerHTML = Object.entries(all).map(([k, v]) => {
        const isCustom = !!customProviders[k];
        const hasKey = !!providerKeys[k];
        const delBtn = isCustom
          ? `<button class="pdel" onclick="deleteCustomProvider(event,'${k}')" title="删除此提供商">✕</button>`
          : '';
        const keyDot = hasKey
          ? `<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--green);margin-left:4px;vertical-align:middle" title="已保存 API Key"></span>`
          : '';
        return `<div class="provider-btn ${k === selectedProvider ? 'selected' : ''}" onclick="selectProvider('${k}')">
      ${delBtn}
      <div class="pname">${v.name || k}${keyDot}</div>
      <div class="pdesc">${isCustom ? '自定义' : descriptions[k] || ''}</div>
    </div>`;
      }).join('')
        + `<div class="add-provider-btn" onclick="showAddProviderForm()">➕ 添加提供商</div>`;
    }

    function showAddProviderForm() {
      const form = document.getElementById('addProviderForm');
      form.classList.add('show');
      document.getElementById('apfName').focus();
    }

    function hideAddProviderForm() {
      document.getElementById('addProviderForm').classList.remove('show');
      ['apfName', 'apfModel', 'apfBaseUrl', 'apfDocs'].forEach(id => document.getElementById(id).value = '');
    }

    function saveCustomProvider() {
      const name = document.getElementById('apfName').value.trim();
      const model = document.getElementById('apfModel').value.trim();
      const baseUrl = document.getElementById('apfBaseUrl').value.trim();
      const docs = document.getElementById('apfDocs').value.trim();
      if (!name) { toast('请填写提供商名称', 'fail'); document.getElementById('apfName').focus(); return; }
      if (!model) { toast('请填写默认模型', 'fail'); document.getElementById('apfModel').focus(); return; }
      if (!baseUrl) { toast('请填写 Base URL', 'fail'); document.getElementById('apfBaseUrl').focus(); return; }

      // key = 小写英文+数字，冲突时加数字后缀
      let key = name.toLowerCase().replace(/[^a-z0-9]/g, '').substring(0, 20) || 'custom' + Date.now();
      if (MODEL_PRESETS[key] || (customProviders[key] && customProviders[key].name !== name)) {
        key = 'cp_' + Date.now();
      }
      customProviders[key] = { name, base_url: baseUrl, model, docs, key_env: '' };
      saveCustomProviders();
      hideAddProviderForm();
      renderProviderGrid();
      // 自动选中刚添加的
      selectProvider(key);
      toast(`已添加提供商「${name}」`);
    }

    function deleteCustomProvider(e, key) {
      e.stopPropagation();
      const p = customProviders[key];
      if (!p) return;
      showConfirm('删除提供商', `确定删除「${p.name}」吗？已保存的 API Key 不受影响。`, () => {
        delete customProviders[key];
        saveCustomProviders();
        if (selectedProvider === key) selectedProvider = '';
        renderProviderGrid();
        toast(`已删除提供商「${p.name}」`);
      });
    }

    function syncModelTagHighlight(val) {
      document.querySelectorAll('.model-tag').forEach(t => {
        t.classList.toggle('active', t.textContent.trim() === val);
      });
    }

    function renderModelTags(models, currentModel) {
      const list = document.getElementById('modelTagList');
      if (!list) return;
      if (!models || !models.length) { list.innerHTML = ''; return; }
      list.innerHTML = models.map(m => `
    <span class="model-tag ${m === currentModel ? 'active' : ''}" onclick="pickModel('${m}')">${m}</span>
  `).join('');
    }

    function pickModel(m) {
      document.getElementById('cfgModel').value = m;
      // 更新标签高亮
      document.querySelectorAll('.model-tag').forEach(t => {
        t.classList.toggle('active', t.textContent.trim() === m);
      });
    }

    function selectProvider(key) {
      selectedProvider = key;
      const preset = getMergedPresets()[key];
      if (!preset) return;
      renderProviderGrid();
      document.getElementById('cfgBaseUrl').value = preset.base_url || '';
      document.getElementById('cfgModel').value = preset.model || '';
      renderModelTags(preset.models || [], preset.model || '');
      const docsHint = document.getElementById('cfgDocsHint');
      docsHint.innerHTML = preset.docs ? `获取 API Key: <a href="${preset.docs}" target="_blank" style="color:var(--accent)">${preset.docs}</a>` : ''
      document.getElementById('testResult').className = 'test-result';

      // 自动回填该提供商已缓存的 Key（只有当选中了具体提供商时才回填）
      const apiKeyInput = document.getElementById('cfgApiKey');
      const keyStatus = document.getElementById('cfgKeyStatus');
      if (key) {
        const cachedKey = getProviderKey(key);
        if (cachedKey) {
          apiKeyInput.value = cachedKey;
          apiKeyInput.placeholder = '已自动填入已保存的 Key';
          if (keyStatus) keyStatus.textContent = '✓ 已配置';
        } else {
          apiKeyInput.value = '';
          apiKeyInput.placeholder = 'sk-...（此提供商暂无保存的 Key）';
          if (keyStatus) keyStatus.textContent = '';
        }
      } else {
        // 未选择提供商时清空
        apiKeyInput.value = '';
        apiKeyInput.placeholder = '请先选择 API 提供商';
        if (keyStatus) keyStatus.textContent = '';
      }
    }

    async function loadCurrentConfig() {
      try {
        const r = await fetch('/model/config');
        const d = await r.json();
        selectedProvider = d.provider || '';

        // 优先用本地缓存的明文 Key 回填（方便直接切换）
        // 注意：如果没有选择提供商，不清空输入框，避免显示其他提供商的key
        const cachedKey = selectedProvider ? getProviderKey(selectedProvider) : '';
        const maskedKey = d.api_key || '';
        const apiKeyInput = document.getElementById('cfgApiKey');
        const keyStatus = document.getElementById('cfgKeyStatus');

        if (!selectedProvider) {
          // 未选择提供商时，清空key输入，不显示任何key
          apiKeyInput.value = '';
          apiKeyInput.placeholder = '请先选择 API 提供商';
          if (keyStatus) keyStatus.textContent = '';
        } else if (cachedKey) {
          apiKeyInput.value = cachedKey;
          apiKeyInput.placeholder = '已自动填入已保存的 Key';
          if (keyStatus) keyStatus.textContent = '✓ 已配置';
        } else {
          apiKeyInput.value = '';
          apiKeyInput.placeholder = maskedKey
            ? `当前已配置：${maskedKey}（填入完整 Key 并保存后可自动切换）`
            : 'sk-...';
          if (keyStatus) keyStatus.textContent = maskedKey ? '✓ 已配置' : '';
        }

        document.getElementById('cfgBaseUrl').value = d.base_url || '';
        document.getElementById('cfgModel').value = d.model || '';
        document.getElementById('cfgProxy').value = d.proxy || '';

        // 渲染当前提供商的模型列表，并高亮当前使用中的模型
        const preset = getMergedPresets()[selectedProvider] || {};
        renderModelTags(preset.models || [], d.model || '');

        renderProviderGrid();
        updateModelIndicator(d);
      } catch (e) { }
    }

    async function saveModelConfig() {
      const key = document.getElementById('cfgApiKey').value.trim();
      const baseUrl = document.getElementById('cfgBaseUrl').value.trim();
      const model = document.getElementById('cfgModel').value.trim();
      const proxy = document.getElementById('cfgProxy').value.trim();

      if (!baseUrl) { toast('Base URL 不能为空', 'fail'); return; }
      if (!model) { toast('Model Name 不能为空', 'fail'); return; }

      // 若填了 Key，缓存到本地（供之后切换自动回填）
      if (key) {
        providerKeys[selectedProvider] = key;
        saveProviderKeys();
      }

      try {
        const r = await fetch('/model/config', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: selectedProvider, api_key: key, base_url: baseUrl, model, proxy })
        });
        const d = await r.json();
        if (!r.ok) { toast(d.detail || '保存失败', 'fail'); return; }
        toast(d.message);
        closeSettings();
        refreshModelIndicator();
      } catch (e) { toast('保存失败: ' + e.message, 'fail'); }
    }

    async function testConnection() {
      const key = document.getElementById('cfgApiKey').value.trim();
      const baseUrl = document.getElementById('cfgBaseUrl').value.trim();
      const model = document.getElementById('cfgModel').value.trim();
      const proxy = document.getElementById('cfgProxy').value.trim();
      const el = document.getElementById('testResult');

      if (!baseUrl || !model) { el.className = 'test-result fail'; el.textContent = '请先填写 Base URL 和 Model Name'; el.style.display = 'block'; return; }
      // key 未填时尝试用已保存的 key 测试
      let testKey = key;
      if (!testKey) {
        try {
          const r = await fetch('/model/config');
          const d = await r.json();
          // 服务端返回的是脱敏 key，无法直接用于测试，提示用户填入
          el.className = 'test-result fail';
          el.textContent = '测试需要填写完整 API Key（已保存的 Key 已脱敏，无法直接测试）';
          el.style.display = 'block';
          return;
        } catch (e) { }
      }

      el.className = 'test-result'; el.textContent = '测试中...'; el.style.display = 'block';

      try {
        const r = await fetch('/model/test', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: selectedProvider, api_key: testKey, base_url: baseUrl, model, proxy })
        });
        const d = await r.json();
        el.className = `test-result ${r.ok ? 'ok' : 'fail'}`;
        el.textContent = d.message || d.detail;
      } catch (e) {
        el.className = 'test-result fail';
        el.textContent = '测试失败: ' + e.message;
      }
    }

    async function refreshModelIndicator() {
      try {
        const r = await fetch('/model/config');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const d = await r.json();
        updateModelIndicator(d);
      } catch (e) {
        // 获取配置失败时不要一直显示"加载中"，显示提示
        const el = document.getElementById('modelLabel');
        if (el && el.textContent === '加载中...') el.textContent = '点击配置模型';
      }
    }

    function updateModelIndicator(cfg) {
      if (!cfg) return;
      const preset = getMergedPresets()[cfg.provider] || {};
      const providerName = preset.name || cfg.provider;
      const modelName = cfg.model;

      // 如果没有配置，显示问号
      if (!providerName && !modelName) {
        document.getElementById('modelLabel').textContent = '?';
        document.getElementById('modelLabel').title = '未配置模型，点击配置';
        document.getElementById('modelDot').style.background = 'var(--red)';
        return;
      }

      const label = `${providerName || '?'} · ${modelName || '?'}`;
      document.getElementById('modelLabel').textContent = label;
      document.getElementById('modelLabel').title = label;
      document.getElementById('modelDot').style.background = 'var(--green)';
    }

    // ═══════════════════════════════════════════════
    // 初始化
    // ═══════════════════════════════════════════════
    async function init() {
      loadCustomProviders();    // 从 localStorage 加载自定义提供商（必须在 loadPresets 前）
      loadProviderKeys();       // 从 localStorage 加载各提供商 API Key 缓存
      await loadPresets();      // loadPresets 内部会调 refreshModelIndicator
      loadCustomTags();         // 从 localStorage 加载自定义快捷指令
      selectOS('linux');   // 默认 Linux 模式，正确渲染选中状态
    }

    init();
