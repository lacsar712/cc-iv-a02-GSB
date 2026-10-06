<template>
  <main>
    <h1>光伏组串IV扫描台</h1>
    <div v-if="!session">
      <p class="sub">扫描员提交开路电压、短路电流与填充因子；通知通道叫醒工人出结论。登录框已预填可写账号 scanner / scan123456。</p>
      <section>
        <label>用户名</label><input v-model="loginUser" autocomplete="off" />
        <label>密码</label><input type="password" v-model="loginPass" autocomplete="off" />
        <button :disabled="loading" @click="login">登录</button>
        <p v-if="error" class="err">{{ error }}</p>
      </section>
    </div>
    <div v-else>
      <nav class="topnav">
        <button class="tab" :class="{ active: tab === 'scan' }" @click="tab = 'scan'">扫描台</button>
        <button class="tab" :class="{ active: tab === 'bands' }" @click="openBands">温度补偿</button>
        <span class="who">已登录：{{ session.username }}（{{ isWriter ? "可提交" : "只读" }}）</span>
        <button class="secondary" @click="logout">退出</button>
      </nav>

      <template v-if="tab === 'scan'">
        <section>
          <button class="secondary" @click="refresh">刷新列表</button>
        </section>
        <section v-if="isWriter">
          <label>组串编号</label><input v-model="stringCode" placeholder="例如 阵列C-串05" />
          <label>开路电压 V</label><input type="number" step="0.1" v-model="voc" />
          <label>短路电流 A</label><input type="number" step="0.1" v-model="isc" />
          <label>填充因子</label><input type="number" step="0.01" v-model="ff" />
          <label>温带（必选，漏点整笔退回）</label>
          <div v-if="bands.length" class="bandpick">
            <label v-for="b in bands" :key="b.band" class="radio">
              <input type="radio" name="band" :value="b.band" v-model="pickedBand" />
              {{ b.band }} [{{ b.ff_min }}, {{ b.ff_max }}]
            </label>
          </div>
          <p v-else class="muted">还没设温带</p>
          <button :disabled="loading || !bands.length" @click="submit">提交扫描</button>
          <p v-if="error" class="err">{{ error }}</p>
        </section>
        <section>
          <table>
            <thead>
              <tr><th>编号</th><th>组串</th><th>Voc</th><th>Isc</th><th>FF</th><th>温带</th><th>状态</th><th>结论</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in logs" :key="row.id">
                <td>{{ row.id }}</td>
                <td>{{ row.string_code }}</td>
                <td>{{ row.voc_v }}</td>
                <td>{{ row.isc_a }}</td>
                <td>{{ row.fill_factor }}</td>
                <td>{{ row.band || "—" }}</td>
                <td><span class="tag" :class="row.status === 'pending' ? 'pending' : 'ok'">{{ row.status === 'pending' ? '待处理' : '已完成' }}</span></td>
                <td><span v-if="row.verdict" class="tag" :class="row.verdict === '合格' ? 'ok' : 'bad'">{{ row.verdict }}</span><span v-else>—</span></td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>

      <template v-else>
        <section>
          <h2>温带</h2>
          <p v-if="!bands.length" class="muted">还没设温带</p>
          <div v-for="b in bands" :key="b.band" class="bandrow">
            <strong>{{ b.band }}</strong>
            <template v-if="isWriter">
              <input type="number" step="0.01" v-model="bandEdits[b.band].ff_min" class="lim" />
              <span>至</span>
              <input type="number" step="0.01" v-model="bandEdits[b.band].ff_max" class="lim" />
              <button :disabled="loading" @click="saveBand(b.band)">保存</button>
            </template>
            <span v-else>闭区间 [{{ b.ff_min }}, {{ b.ff_max }}]</span>
            <span class="muted">最近改动：{{ b.updated_by || "—" }}</span>
          </div>
          <p v-if="bandError" class="err">{{ bandError }}</p>
        </section>
        <section>
          <h2>改带履历</h2>
          <p v-if="!history.length" class="muted">还没改过带</p>
          <table v-else>
            <thead>
              <tr><th>编号</th><th>温带</th><th>原区间</th><th>新区间</th><th>改带人</th><th>时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="h in history" :key="h.id">
                <td>{{ h.id }}</td>
                <td>{{ h.band }}</td>
                <td>{{ h.old_min === null ? "—" : `[${h.old_min}, ${h.old_max}]` }}</td>
                <td>[{{ h.new_min }}, {{ h.new_max }}]</td>
                <td>{{ h.changed_by }}</td>
                <td>{{ fmtTime(h.changed_at) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
        <section>
          <h2>认领抄本</h2>
          <p v-if="!ledger.length" class="muted">还没有认领记录</p>
          <table v-else>
            <thead>
              <tr><th>编号</th><th>扫描单</th><th>温带</th><th>抄入下限</th><th>抄入上限</th><th>认领方</th><th>时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="l in ledger" :key="l.id">
                <td>{{ l.id }}</td>
                <td>{{ l.scan_id }}</td>
                <td>{{ l.band }}</td>
                <td>{{ l.ff_min }}</td>
                <td>{{ l.ff_max }}</td>
                <td>{{ l.claimed_by }}</td>
                <td>{{ fmtTime(l.claimed_at) }}</td>
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
const ledger = ref([]);
const bandEdits = ref({});
const loginUser = ref("scanner");
const loginPass = ref("scan123456");
const stringCode = ref("");
const voc = ref("");
const isc = ref("");
const ff = ref("");
const pickedBand = ref("");
const error = ref("");
const bandError = ref("");
const loading = ref(false);
let timer;
const isWriter = computed(() => session.value?.role === "writer");
function headers() {
  return session.value ? { Authorization: "Bearer " + session.value.token } : {};
}
function fmtTime(t) {
  return t ? new Date(t).toLocaleString() : "—";
}
async function refresh() {
  if (!session.value) return;
  const res = await fetch("/api/logs", { headers: headers() });
  if (res.status === 401) { logout(); return; }
  if (res.ok) logs.value = await res.json();
}
async function loadBands() {
  if (!session.value) return;
  const res = await fetch("/api/bands", { headers: headers() });
  if (res.status === 401) { logout(); return; }
  if (res.ok) {
    bands.value = await res.json();
    const edits = {};
    for (const b of bands.value) edits[b.band] = { ff_min: b.ff_min, ff_max: b.ff_max };
    bandEdits.value = edits;
  }
}
async function loadBandPage() {
  if (!session.value) return;
  await loadBands();
  const [h, l] = await Promise.all([
    fetch("/api/bands/history", { headers: headers() }),
    fetch("/api/claim-ledger", { headers: headers() }),
  ]);
  if (h.ok) history.value = await h.json();
  if (l.ok) ledger.value = await l.json();
}
function openBands() {
  tab.value = "bands";
  loadBandPage();
}
async function saveBand(band) {
  bandError.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/bands", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({
        band,
        ff_min: Number(bandEdits.value[band].ff_min),
        ff_max: Number(bandEdits.value[band].ff_max),
      }),
    });
    const data = await res.json();
    if (!res.ok) { bandError.value = data.detail || "改带失败"; return; }
    await loadBandPage();
  } catch { bandError.value = "改带时网络异常"; }
  finally { loading.value = false; }
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
    await Promise.all([refresh(), loadBands()]);
    timer = setInterval(() => {
      refresh();
      if (tab.value === "bands") loadBandPage();
    }, 2000);
  } catch { error.value = "无法连接接口"; }
  finally { loading.value = false; }
}
function logout() {
  if (timer) clearInterval(timer);
  session.value = null;
  logs.value = [];
  bands.value = [];
  history.value = [];
  ledger.value = [];
  pickedBand.value = "";
  localStorage.removeItem("pv_session");
}
async function submit() {
  error.value = "";
  if (!pickedBand.value) { error.value = "必须点选温带，漏点整笔退回"; return; }
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
        band: pickedBand.value,
      }),
    });
    const data = await res.json();
    if (!res.ok) { error.value = data.detail || "提交失败"; return; }
    stringCode.value = voc.value = isc.value = ff.value = "";
    await refresh();
  } catch { error.value = "提交时网络异常"; }
  finally { loading.value = false; }
}
onMounted(() => {
  const raw = localStorage.getItem("pv_session");
  if (raw) {
    try {
      session.value = JSON.parse(raw);
      refresh();
      loadBands();
      timer = setInterval(() => {
        refresh();
        if (tab.value === "bands") loadBandPage();
      }, 2000);
    } catch { localStorage.removeItem("pv_session"); }
  }
});
onUnmounted(() => { if (timer) clearInterval(timer); });
</script>
<style>
body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #052e16; color: #ecfdf5; }
main { max-width: 980px; margin: 0 auto; padding: 1.5rem; }
h1 { color: #86efac; margin: 0 0 0.25rem; }
h2 { color: #86efac; font-size: 1.05rem; margin: 0 0 0.6rem; }
.sub { color: #a7f3d0; margin-bottom: 1.25rem; }
section { background: #14532d; border: 1px solid #166534; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1rem; }
label { display: block; font-size: 0.85rem; margin-bottom: 0.25rem; }
input { width: 100%; box-sizing: border-box; padding: 0.5rem 0.65rem; border-radius: 6px; border: 1px solid #4ade80; background: #022c22; color: #ecfdf5; margin-bottom: 0.75rem; }
button { cursor: pointer; padding: 0.5rem 1rem; border: none; border-radius: 6px; background: #16a34a; color: #fff; font-weight: 600; margin-right: 0.4rem; }
button.secondary { background: #365314; }
.err { color: #fecaca; }
.muted { color: #a7f3d0; opacity: 0.75; font-size: 0.85rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.45rem; border-bottom: 1px solid #166534; }
.tag { padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.8rem; }
.ok { background: #14532d; color: #bbf7d0; }
.bad { background: #7f1d1d; color: #fecaca; }
.pending { background: #854d0e; color: #fde68a; }
.topnav { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 1rem; }
.topnav .who { margin-left: auto; color: #a7f3d0; font-size: 0.85rem; }
.tab { background: #365314; }
.tab.active { background: #16a34a; }
.bandpick { display: flex; gap: 1rem; margin-bottom: 0.75rem; }
.radio { display: flex; align-items: center; gap: 0.3rem; font-size: 0.9rem; }
.radio input { width: auto; margin: 0; }
.bandrow { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.6rem; }
.bandrow .lim { width: 6rem; margin-bottom: 0; }
</style>
