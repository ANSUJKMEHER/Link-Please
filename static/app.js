// LinkPlease Dashboard Client Logic

let lastSimulationRunId = null;

document.addEventListener("DOMContentLoaded", () => {
  initPresets();
  initForms();
  loadRules();
  startLivePolling();
});

// 1. Preset Chips Handler
function initPresets() {
  document.querySelectorAll(".preset-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      document.getElementById("ruleKeyword").value = chip.dataset.keyword;
      document.getElementById("ruleMessage").value = chip.dataset.msg;
    });
  });
}

// 2. Forms & Actions
function initForms() {
  // Create Rule
  document.getElementById("createRuleForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const keyword = document.getElementById("ruleKeyword").value.trim();
    const dm_message = document.getElementById("ruleMessage").value.trim();
    
    if (!keyword || !dm_message) return;

    try {
      const res = await fetch("/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keyword, dm_message })
      });
      if (res.ok) {
        document.getElementById("ruleKeyword").value = "";
        document.getElementById("ruleMessage").value = "";
        loadRules();
        fetchStats();
      } else {
        const err = await res.text();
        alert("Failed to create rule: " + err);
      }
    } catch (err) {
      console.error(err);
    }
  });

  // Direct Webhook Tester (Created)
  document.getElementById("testWebhookForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const userId = document.getElementById("testUserId").value.trim();
    const username = document.getElementById("testUsername").value.trim();
    const text = document.getElementById("testCommentText").value.trim();
    
    const eventId = "evt_" + Math.random().toString(36).substring(2, 10);
    const commentId = "cmt_" + Math.random().toString(36).substring(2, 10);

    const payload = {
      event_id: eventId,
      event_type: "comment.created",
      sent_at: new Date().toISOString(),
      data: {
        comment_id: commentId,
        post_id: "post_test_99",
        text: text,
        created_at: new Date().toISOString(),
        from: {
          user_id: userId,
          username: username
        }
      }
    };

    await sendWebhookPayload(payload);
  });

  // Direct Webhook Tester (Deleted)
  document.getElementById("btnSendDeleted").addEventListener("click", async () => {
    const commentId = prompt("Enter comment_id to cancel/delete:", "cmt_test_123");
    if (!commentId) return;

    const payload = {
      event_id: "evt_del_" + Math.random().toString(36).substring(2, 10),
      event_type: "comment.deleted",
      sent_at: new Date().toISOString(),
      data: {
        comment_id: commentId
      }
    };

    await sendWebhookPayload(payload);
  });

  // Simulation Form
  document.getElementById("simulationForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const webhook_url = document.getElementById("simWebhookUrl").value.trim();
    const count = parseInt(document.getElementById("simCount").value);
    const duration_seconds = parseInt(document.getElementById("simDuration").value);

    try {
      const btn = document.getElementById("btnStartSim");
      btn.innerText = "Launching...";
      btn.disabled = true;

      const res = await fetch("/api/simulate/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ webhook_url, count, duration_seconds })
      });

      btn.innerText = "Launch 500-Event Simulation";
      btn.disabled = false;

      if (res.ok) {
        const data = await res.json();
        lastSimulationRunId = data.run_id;
        document.getElementById("simResults").classList.remove("hidden");
        document.getElementById("simRunId").innerText = lastSimulationRunId;
        document.getElementById("simTruthContent").innerText = "Simulation running... Polling truth in 10s.";
      } else {
        const err = await res.text();
        alert("Simulation failed to start: " + err);
      }
    } catch (err) {
      console.error(err);
      alert("Error starting simulation: " + err);
    }
  });

  // Fetch Truth for Last Run
  document.getElementById("btnFetchTruth").addEventListener("click", async () => {
    const runId = lastSimulationRunId || prompt("Enter run_id to fetch truth for:");
    if (!runId) return;

    try {
      const res = await fetch(`/api/simulate/${runId}/truth`);
      if (res.ok) {
        const truth = await res.json();
        document.getElementById("simResults").classList.remove("hidden");
        document.getElementById("simRunId").innerText = runId;
        document.getElementById("simTruthContent").innerText = JSON.stringify(truth, null, 2);
      } else {
        alert("Could not fetch truth: " + (await res.text()));
      }
    } catch (err) {
      console.error(err);
    }
  });

  // Reset State
  document.getElementById("btnResetAll").addEventListener("click", async () => {
    if (!confirm("Are you sure you want to reset all stats, rules, and queues?")) return;
    try {
      const res = await fetch("/api/reset", { method: "POST" });
      if (res.ok) {
        loadRules();
        fetchStats();
        fetchQueue();
      }
    } catch (err) {
      console.error(err);
    }
  });

  // Manual refresh queue
  document.getElementById("btnRefreshQueue").addEventListener("click", fetchQueue);
}

async function sendWebhookPayload(payload) {
  try {
    const res = await fetch("/webhook", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    fetchStats();
    fetchQueue();
  } catch (err) {
    console.error(err);
    alert("Webhook request error: " + err);
  }
}

// 3. Load & Render Rules
async function loadRules() {
  try {
    const res = await fetch("/rules");
    if (!res.ok) return;
    const rules = await res.json();

    document.getElementById("rulesCount").innerText = rules.length;
    const listEl = document.getElementById("rulesList");

    if (rules.length === 0) {
      listEl.innerHTML = `<div class="empty-placeholder">No rules created yet. Add one above.</div>`;
      return;
    }

    listEl.innerHTML = rules.map(r => `
      <div class="rule-item">
        <div class="rule-info">
          <span class="rule-keyword-badge">${escapeHtml(r.keyword)}</span>
          <span class="rule-msg-text">${escapeHtml(r.dm_message)}</span>
        </div>
        <button class="btn-delete-rule" onclick="deleteRule('${r.rule_id}')" title="Delete Rule">🗑️</button>
      </div>
    `).join("");
  } catch (err) {
    console.error("Error loading rules:", err);
  }
}

async function deleteRule(ruleId) {
  try {
    await fetch(`/rules/${ruleId}`, { method: "DELETE" });
    loadRules();
  } catch (err) {
    console.error(err);
  }
}

// 4. Live Stats & Rate Limiter Polling
async function fetchStats() {
  try {
    const res = await fetch("/stats");
    if (res.ok) {
      const stats = await res.json();
      document.getElementById("statSent").innerText = stats.sent;
      document.getElementById("statFailed").innerText = stats.failed;
      document.getElementById("statQueued").innerText = stats.queued;
      document.getElementById("statDuplicates").innerText = stats.duplicates_blocked;
    }

    // Fetch Rate Limiter Internal Status
    const rateRes = await fetch("/api/rate_limiter");
    if (rateRes.ok) {
      const rl = await rateRes.json();
      const active = rl.active_requests_in_window || 0;
      const max = rl.max_requests || 10;
      const pct = Math.min(100, Math.round((active / max) * 100));

      document.getElementById("rateBadge").innerText = `${active} / ${max} Active`;
      document.getElementById("rateProgressBar").style.width = `${pct}%`;
      document.getElementById("rateWindowInfo").innerText = `Rolling 60s Window: ${active} slots used (${max - active} available)`;

      const cooldownEl = document.getElementById("cooldownIndicator");
      if (rl.cooldown_active) {
        cooldownEl.classList.remove("hidden");
        cooldownEl.innerText = `429 Cooldown: ${rl.cooldown_remaining_seconds.toFixed(1)}s remaining`;
      } else {
        cooldownEl.classList.add("hidden");
      }
    }
  } catch (err) {
    console.error(err);
  }
}

// 5. Live Queue Inspector
async function fetchQueue() {
  try {
    const res = await fetch("/api/queue?limit=25");
    if (!res.ok) return;
    const items = await res.json();

    const tbody = document.getElementById("queueTableBody");
    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-table">No DMs in queue.</td></tr>`;
      return;
    }

    tbody.innerHTML = items.map(item => `
      <tr>
        <td><strong>${escapeHtml(item.recipient_user_id)}</strong></td>
        <td>${escapeHtml(item.comment_id)}</td>
        <td><span class="badge-status ${item.status}">${escapeHtml(item.status)}</span></td>
        <td>${item.attempts} / 5</td>
        <td>${escapeHtml(item.dm_id || '-')}</td>
      </tr>
    `).join("");
  } catch (err) {
    console.error("Error fetching queue:", err);
  }
}

function startLivePolling() {
  fetchStats();
  fetchQueue();
  setInterval(() => {
    fetchStats();
    fetchQueue();
  }, 2000);
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
