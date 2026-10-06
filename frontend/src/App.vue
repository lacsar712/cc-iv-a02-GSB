<template>
  <main>
    <h1>光伏组串IV扫描台</h1>
    <nav v-if="session" class="tabs">
      <button :class="{ active: tab === 'scan' }" @click="tab = 'scan'">扫描录入</button>
      <button :class="{ active: tab === 'comp' }" @click="openComp">温度补偿</button>
    </nav>
    <div v-if="!session">
      <p class="sub">扫描员提交开路电压、短路电流与填充因子，并必须点选温带；通知通道叫醒工人，工人认领瞬间抄录该温带现行闭区间再出结论。登录框已预填可写账号 scanner / scan123456。</p>
      <section>
        <label>用户名</label><input v-model="loginUser" autocomplete="off" />
        <label>密码</label><input type="password" v-model="loginPass" autocomplete="off" />
        <button :disabled="loading" @click="login">登录</button>
        <p v-if="error" class="err">{{ error }}</p>
      </section>
    </div>
    <div v-else>
      <p class="sub">已登录：{{ session.username }}（{{ isWriter ? "可提交、可改带" : "观察员：只能翻温带和履历，不能改带也不能入队" }}）</p>
      <section>
        <button class="secondary" @click="logout">退出</button>
        <button class="secondary" @click="manualRefresh">刷新</button>
      </section>

      <!-- 扫描录入页 -->
      <template v-if="tab === 'scan'">
        <section v-if="isWriter">
          <label>组串编号</label><input v-model="stringCode" placeholder="例如 阵列C-串05" />
          <label>开路电压 V</label><input type="number" step="0.1" v-model="voc" />
          <label>短路电流 A</label><input type="number" step="0.1" v-model="isc" />
          <label>填充因子</label><input type="number" step="0.01" v-model="ff" />
          <!-- 温带选项与标签全部来自后端 /api/bands，画面不自带第二套名字 -->
          <label class="band-label">温带（必点，漏点整笔退）</label>
          <div class="band-pick">
            <label v-for="b in bands" :key="b.band_key" class="band-opt">
              <input type="radio" name="band" :value="b.band_key" v-model="selectedBand" />
              <span>{{ b.label }}</span>
              <span class="band-range">
                现行闭区间
                <template v-if="b.configured">[{{ b.ff_low }}, {{ b.ff_high }}]</template>
                <template v-else>还没设温带，交了也排队等设带</template>
              </span>
            </label>
          </div>
          <button :disabled="loading" @click="submit">提交扫描</button>
          <p v-if="error" class="err">{{ error }}</p>
        </section>
        <section>
          <table>
            <thead>
              <tr><th>编号</th><th>组串</th><th>入库温带</th><th>Voc</th><th>Isc</th><th>FF</th><th>认领抄本区间</th><th>状态</th><th>结论</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in logs" :key="row.id">
                <td>{{ row.id }}</td>
                <td>{{ row.string_code }}</td>
                <td>{{ row.band_label }}</td>
                <td>{{ row.voc_v }}</td>
                <td>{{ row.isc_a }}</td>
                <td>{{ row.fill_factor }}</td>
                <td>
                  <span v-if="row.ff_low_snap != null">[{{ row.ff_low_snap }}, {{ row.ff_high_snap }}]</span>
                  <span v-else class="dim">待认领</span>
                </td>
                <td><span class="tag" :class="row.status === 'pending' ? 'pending' : 'ok'">{{ row.status === 'pending' ? '待处理' : '已完成' }}</span></td>
                <td><span v-if="row.verdict" class="tag" :class="row.verdict === '合格' ? 'ok' : 'bad'">{{ row.verdict }}</span><span v-else>—</span></td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>

      <!-- 温度补偿专页：上格温带 / 中格改带履历 / 下格认领抄本 -->
      <template v-if="tab === 'comp'">
        <section>
          <h2 class="pane-title">上格 · 现行温带</h2>
          <p class="dim" v-if="!isWriter">观察员只读：可翻温带与履历，改带与入队均不可用。</p>
          <div class="band-cards">
            <div v-for="b in bands" :key="b.band_key" class="band-card">
              <h3>{{ b.label }}</h3>
              <template v-if="b.configured">
                <p>现行闭区间：<b>[{{ b.ff_low }}, {{ b.ff_high }}]</b>（端点含）</p>
                <p class="dim">最近改带人：{{ b.updated_by }} · {{ fmtTime(b.updated_at) }}</p>
              </template>
              <template v-else>
                <p class="unset">还没设温带</p>
              </template>
              <template v-if="isWriter">
                <div class="band-edit">
                  <label>下限
                    <input type="number" step="0.01" min="0" max="1"
                           v-model="drafts[b.band_key].low" />
                  </label>
                  <label>上限
                    <input type="number" step="0.01" min="0" max="1"
                           v-model="drafts[b.band_key].high" />
                  </label>
                  <button @click="saveBand(b)">保存闭区间</button>
                </div>
              </template>
            </div>
          </div>
          <p v-if="compError" class="err">{{ compError }}</p>
        </section>

        <section>
          <h2 class="pane-title">中格 · 改带履历</h2>
          <p v-if="history.length === 0" class="dim">还没有改过带。</p>
          <table v-else>
            <thead>
              <tr><th>时间</th><th>温带</th><th>改前闭区间</th><th>改后闭区间</th><th>操作人</th></tr>
            </thead>
            <tbody>
              <tr v-for="h in history" :key="h.id">
                <td>{{ fmtTime(h.changed_at) }}</td>
                <td>{{ h.label }}</td>
                <td><span v-if="h.low_before != null">[{{ h.low_before }}, {{ h.high_before }}]</span><span v-else class="dim">还没设温带</span></td>
                <td>[{{ h.low_after }}, {{ h.high_after }}]</td>
                <td>{{ h.changed_by }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section>
          <h2 class="pane-title">下格 · 认领抄本</h2>
          <p class="dim">工人认领那一瞬抄进单子的上下限；之后再改带，这些单继续按抄本走。</p>
          <p v-if="transcripts.length === 0" class="dim">还没有被认领的单。</p>
          <table v-else>
            <thead>
              <tr><th>认领时间</th><th>编号</th><th>组串</th><th>温带</th><th>FF</th><th>抄本闭区间</th><th>结论</th></tr>
            </thead>
            <tbody>
              <tr v-for="t in transcripts" :key="t.id">
                <td>{{ fmtTime(t.claimed_at) }}</td>
                <td>{{ t.id }}</td>
                <td>{{ t.string_code }}</td>
                <td>{{ t.band_label }}</td>
                <td>{{ t.fill_factor }}</td>
                <td>[{{ t.ff_low_snap }}, {{ t.ff_high_snap }}]</td>
                <td><span class="tag" :class="t.verdict === '合格' ? 'ok' : 'bad'">{{ t.verdict }}</span></td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>
    </div>
  </main>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
const session = ref(null);
const tab = ref("scan");
const logs = ref([]);
const bands = ref([]);
const history = ref([]);
const transcripts = ref([]);
const drafts = ref({ high: { low: "", high: "" }, low: { low: "", high: "" } });
const loginUser = ref("scanner");
const loginPass = ref("scan123456");
const stringCode = ref("");
const voc = ref("");
const isc = ref("");
const ff = ref("");
const selectedBand = ref("");
const error = ref("");
const compError = ref("");
const loading = ref(false);
let timer;
const isWriter = computed(() => session.value?.role === "writer");

function headers() {
  return session.value ? { Authorization: "Bearer " + session.value.token } : {};
}
function fmtTime(iso) {
  if (!iso) return "—";
  return iso.replace("T", " ").slice(0, 19);
}

async function refreshLogs() {
  if (!session.value) return;
  const res = await fetch("/api/logs", { headers: headers() });
  if (res.status === 401) { logout(); return; }
  if (res.ok) logs.value = await res.json();
}
async function refreshBands() {
  const res = await fetch("/api/bands", { headers: headers() });
  if (res.status === 401) { logout(); return; }
  if (!res.ok) return;
  const list = await res.json();
  bands.value = list;
  // 改带输入框只在还没动过时跟随现行值预填，避免冲掉正在输入的数字
  for (const b of list) {
    if (!drafts.value[b.band_key]) drafts.value[b.band_key] = { low: "", high: "" };
    const d = drafts.value[b.band_key];
    if (d.low === "" && d.high === "" && b.configured) {
      d.low = String(b.ff_low);
      d.high = String(b.ff_high);
    }
  }
}
async function refreshHistory() {
  const res = await fetch("/api/band-history", { headers: headers() });
  if (res.ok) history.value = await res.json();
}
async function refreshTranscripts() {
  const res = await fetch("/api/transcripts", { headers: headers() });
  if (res.ok) transcripts.value = await res.json();
}
function manualRefresh() {
  refreshLogs();
  if (tab.value === "comp") { refreshBands(); refreshHistory(); refreshTranscripts(); }
}
async function openComp() {
  tab.value = "comp";
  await Promise.all([refreshBands(), refreshHistory(), refreshTranscripts()]);
}

async function login() {
  error.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: loginUser.value, password: loginPass.value }),
    });
    const data = await res.json();
    if (!res.ok) { error.value = data.detail || "登录失败"; return; }
    session.value = { token: data.access_token, username: data.username, role: data.role };
    localStorage.setItem("pv_session", JSON.stringify(session.value));
    await Promise.all([refreshLogs(), refreshBands()]);
    timer = setInterval(tick, 2000);
  } catch { error.value = "无法连接接口"; }
  finally { loading.value = false; }
}
function tick() {
  refreshLogs();
  if (tab.value === "comp") { refreshBands(); refreshHistory(); refreshTranscripts(); }
}
function logout() {
  if (timer) clearInterval(timer);
  session.value = null;
  logs.value = [];
  bands.value = [];
  history.value = [];
  transcripts.value = [];
  tab.value = "scan";
  localStorage.removeItem("pv_session");
}
async function submit() {
  error.value = "";
  // 前端先拦一次；后端仍会独立拒绝漏点单，保证整笔不入队
  if (!selectedBand.value) { error.value = "必须点选温带（高温带/低温带），漏点整笔拒收"; return; }
  loading.value = true;
  try {
    const res = await fetch("/api/logs", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({
        string_code: stringCode.value,
        voc_v: Number(voc.value),
        isc_a: Number(isc.value),
        fill_factor: Number(ff.value),
        band_key: selectedBand.value,
      }),
    });
    const data = await res.json();
    if (!res.ok) { error.value = data.detail || "提交失败"; return; }
    stringCode.value = voc.value = isc.value = ff.value = "";
    selectedBand.value = "";
    await refreshLogs();
  } catch { error.value = "提交时网络异常"; }
  finally { loading.value = false; }
}
async function saveBand(b) {
  compError.value = "";
  const d = drafts.value[b.band_key];
  const low = Number(d.low);
  const high = Number(d.high);
  if (d.low === "" || d.high === "" || Number.isNaN(low) || Number.isNaN(high)) {
    compError.value = `${b.label}：上下限必须填数字`;
    return;
  }
  if (!(0 <= low && low <= high && high <= 1)) {
    compError.value = `${b.label}：需满足 0 ≤ 下限 ≤ 上限 ≤ 1`;
    return;
  }
  const res = await fetch(`/api/bands/${b.band_key}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...headers() },
    body: JSON.stringify({ ff_low: low, ff_high: high }),
  });
  const data = await res.json();
  if (!res.ok) { compError.value = data.detail || "改带失败"; return; }
  await Promise.all([refreshBands(), refreshHistory(), refreshTranscripts()]);
}
onMounted(() => {
  const raw = localStorage.getItem("pv_session");
  if (raw) {
    try {
      session.value = JSON.parse(raw);
      refreshLogs();
      refreshBands();
      timer = setInterval(tick, 2000);
    } catch { localStorage.removeItem("pv_session"); }
  }
});
onUnmounted(() => { if (timer) clearInterval(timer); });
</script>
<style>
body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #052e16; color: #ecfdf5; }
main { max-width: 980px; margin: 0 auto; padding: 1.5rem; }
h1 { color: #86efac; margin: 0 0 0.75rem; }
h2 { font-size: 1rem; margin: 0 0 0.75rem; }
h3 { margin: 0 0 0.5rem; color: #86efac; }
.sub { color: #a7f3d0; margin-bottom: 1.25rem; }
.tabs { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
.tabs button { background: #14532d; border: 1px solid #166534; }
.tabs button.active { background: #16a34a; }
section { background: #14532d; border: 1px solid #166534; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1rem; }
.pane-title { color: #bbf7d0; }
label { display: block; font-size: 0.85rem; margin-bottom: 0.25rem; }
input[type="number"], input:not([type]) { width: 100%; box-sizing: border-box; padding: 0.5rem 0.65rem; border-radius: 6px; border: 1px solid #4ade80; background: #022c22; color: #ecfdf5; margin-bottom: 0.75rem; }
button { cursor: pointer; padding: 0.5rem 1rem; border: none; border-radius: 6px; background: #16a34a; color: #fff; font-weight: 600; margin-right: 0.4rem; }
button.secondary { background: #365314; }
.err { color: #fecaca; }
.dim { color: #86efac99; font-size: 0.85rem; }
.unset { color: #fde68a; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.45rem; border-bottom: 1px solid #166534; }
.tag { padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.8rem; }
.ok { background: #14532d; color: #bbf7d0; }
.bad { background: #7f1d1d; color: #fecaca; }
.pending { background: #854d0e; color: #fde68a; }
.band-label { margin-top: 0.25rem; }
.band-pick { display: flex; flex-direction: column; gap: 0.4rem; margin-bottom: 0.9rem; }
.band-opt { display: flex; align-items: center; gap: 0.5rem; background: #022c22; border: 1px solid #166534; border-radius: 6px; padding: 0.5rem 0.75rem; font-size: 0.9rem; }
.band-opt input { width: auto; margin: 0; }
.band-opt .band-range { color: #a7f3d0; font-size: 0.82rem; }
.band-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 0.9rem; }
.band-card { background: #022c22; border: 1px solid #166534; border-radius: 8px; padding: 0.9rem 1rem; }
.band-edit { display: grid; grid-template-columns: 1fr 1fr auto; gap: 0.5rem; align-items: end; margin-top: 0.6rem; }
.band-edit label { font-size: 0.8rem; }
.band-edit input { margin-bottom: 0; }
.band-edit button { margin-right: 0; white-space: nowrap; }
@media (max-width: 720px) { .band-cards { grid-template-columns: 1fr; } }
</style>
