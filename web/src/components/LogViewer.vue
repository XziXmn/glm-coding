<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { zhCN as copy } from "../locales/zhCN";
import { api } from "../services/api";
import type { LogStreamOption, PublicAccountRecord, RuntimeLogEntry } from "../types/api";

const props = defineProps<{
  show: boolean;
  accounts: PublicAccountRecord[];
}>();

const emit = defineEmits<{
  (e: "update:show", value: boolean): void;
}>();

const streams = ref<LogStreamOption[]>([]);
const stream = ref("global");
const accountId = ref<string | null>(null);
const entries = ref<RuntimeLogEntry[]>([]);
const loading = ref(false);
const total = ref(0);
const truncated = ref(false);
const date = ref("");
const keyword = ref("");
const expanded = ref<Set<number>>(new Set());

const accountOptions = computed(() =>
  props.accounts.map((account) => ({
    label: account.label || account.id,
    value: account.id,
  })),
);

const filteredEntries = computed(() => {
  const kw = keyword.value.trim().toLowerCase();
  if (!kw) return entries.value;
  return entries.value.filter(
    (entry) =>
      entry.message.toLowerCase().includes(kw) ||
      entry.action.toLowerCase().includes(kw) ||
      entry.stage.toLowerCase().includes(kw) ||
      entry.account_id.toLowerCase().includes(kw) ||
      entry.details_text.toLowerCase().includes(kw),
  );
});

const statusType = (status: string): string => {
  const s = status.toLowerCase();
  if (["success", "started", "ready"].includes(s)) return "success";
  if (["failed", "error"].includes(s)) return "error";
  if (["warning", "retry", "retrying", "paused", "pause_requested"].includes(s)) return "warning";
  return "default";
};

async function loadStreams() {
  try {
    const payload = await api.logStreams();
    streams.value = payload.streams;
  } catch {
    streams.value = [
      { value: "global", label: copy.logs.global },
      { value: "account", label: copy.logs.account },
      { value: "captcha", label: copy.logs.captcha },
    ];
  }
}

async function loadLogs() {
  if (!props.show) return;
  loading.value = true;
  expanded.value.clear();
  try {
    const payload = await api.todayLogs(
      accountId.value || undefined,
      stream.value,
    );
    entries.value = payload.entries;
    total.value = payload.total || payload.entries.length;
    truncated.value = payload.truncated || false;
    date.value = payload.date;
  } catch {
    entries.value = [];
    total.value = 0;
    truncated.value = false;
    date.value = "";
  } finally {
    loading.value = false;
  }
}

function toggleExpanded(index: number) {
  if (expanded.value.has(index)) {
    expanded.value.delete(index);
  } else {
    expanded.value.add(index);
  }
}

function close() {
  emit("update:show", false);
}

onMounted(loadStreams);
watch(() => props.show, loadLogs);
watch([stream, accountId], loadLogs);
</script>

<template>
  <n-drawer
    :show="show"
    display-directive="show"
    placement="right"
    width="min(1080px, 96vw)"
    @update:show="emit('update:show', $event)"
  >
    <n-drawer-content :title="copy.app.logsTitle" closable @close="close">
      <div class="logs-toolbar">
        <n-select
          v-model:value="stream"
          :options="streams"
          size="small"
          style="width: 160px"
        />
        <n-select
          v-if="stream === 'account'"
          v-model:value="accountId"
          :options="accountOptions"
          :placeholder="copy.logs.selectAccount"
          clearable
          size="small"
          style="width: 220px"
        />
        <n-input
          v-model:value="keyword"
          :placeholder="copy.logs.searchPlaceholder"
          size="small"
          clearable
          style="width: 240px"
        />
        <span class="logs-meta">
          {{ date }}
          <template v-if="total > 0">
            / {{ copy.logs.total(total) }}
            <template v-if="truncated">{{ copy.logs.truncatedHint }}</template>
          </template>
        </span>
        <n-button
          size="small"
          secondary
          :loading="loading"
          @click="loadLogs"
        >
          {{ copy.app.refreshLogs }}
        </n-button>
      </div>

      <n-spin :show="loading">
        <div v-if="filteredEntries.length === 0" class="logs-empty">
          <n-empty :description="copy.app.noLogs" />
        </div>
        <div v-else class="logs-list">
          <div
            v-for="(entry, index) in filteredEntries"
            :key="index"
            class="log-entry"
            :class="`status-${entry.status}`"
          >
            <div class="log-header" @click="toggleExpanded(index)">
              <n-tag :type="statusType(entry.status)" size="small" round>
                {{ entry.status || "-" }}
              </n-tag>
              <span class="log-time">{{ entry.timestamp }}</span>
              <span v-if="stream !== 'account'" class="log-account">{{ entry.account_id }}</span>
              <span class="log-action">{{ entry.action }}/{{ entry.stage }}</span>
              <span class="log-message">{{ entry.message }}</span>
              <n-button
                v-if="entry.details_text"
                text
                size="tiny"
                class="log-expand"
              >
                {{ expanded.has(index) ? copy.logs.collapse : copy.logs.expand }}
              </n-button>
            </div>
            <pre v-if="expanded.has(index)" class="log-details">{{ entry.details_text }}</pre>
          </div>
        </div>
      </n-spin>
    </n-drawer-content>
  </n-drawer>
</template>
