<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import { zhCN as copy } from "../locales/zhCN";
import type { GlobalSettings } from "../types/api";

const props = defineProps<{
  show: boolean;
  settings: GlobalSettings | null;
  loading: boolean;
}>();

const emit = defineEmits<{
  "update:show": [value: boolean];
  submit: [payload: Partial<GlobalSettings>];
}>();

const local = reactive<GlobalSettings>({
  scheduled_start_time: "09:59:58",
  preview_concurrency: 2,
  preview_concurrency_time: "09:59:59",
  ticket_pool_size: 20,
  ticket_pool_drain_interval_ms: 500,
  stock_monitor_enabled: false,
  auto_probe_on_import: true,
});

const isOpen = computed({
  get: () => props.show,
  set: (value) => emit("update:show", value),
});

watch(
  () => props.settings,
  (next) => {
    if (next) {
      Object.assign(local, next);
    }
  },
  { immediate: true },
);

function submit() {
  emit("submit", { scheduled_start_time: local.scheduled_start_time });
}
</script>

<template>
  <n-modal
    v-model:show="isOpen"
    preset="card"
    class="desk-modal"
    :title="copy.settings.title"
    :bordered="false"
    :segmented="{ content: true }"
  >
    <div class="settings-form">
      <div class="settings-group">
        <strong>{{ copy.settings.groups.schedule }}</strong>
        <label class="setting-row">
          <span>{{ copy.settings.scheduledStartTime }}</span>
          <input
            v-model="local.scheduled_start_time"
            class="time-input"
            type="time"
            step="1"
          />
        </label>
      </div>
    </div>

    <template #footer>
      <div class="modal-actions">
        <n-button secondary @click="isOpen = false">
          {{ copy.settings.cancel }}
        </n-button>
        <n-button type="primary" :loading="loading" @click="submit">
          {{ copy.settings.submit }}
        </n-button>
      </div>
    </template>
  </n-modal>
</template>
