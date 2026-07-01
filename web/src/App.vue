<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { dateZhCN, zhCN as naiveZhCN } from "naive-ui";
import AccountContextModal from "./components/AccountContextModal.vue";
import AccountTable from "./components/AccountTable.vue";
import AppShell from "./components/AppShell.vue";
import DashboardStats from "./components/DashboardStats.vue";
import GlobalSettingsModal from "./components/GlobalSettingsModal.vue";
import ImportAccountModal from "./components/ImportAccountModal.vue";
import LogViewer from "./components/LogViewer.vue";
import ProxyPoolConfigModal from "./components/ProxyPoolConfigModal.vue";
import StatusBanner from "./components/StatusBanner.vue";
import { useDashboard } from "./composables/useDashboard";
import type { AccountDetailResponse, AccountImportPayload } from "./types/api";

const dashboard = useDashboard();
const showImport = ref(false);
const showProxyPoolConfig = ref(false);
const showContext = ref(false);
const showLogs = ref(false);
const showSettings = ref(false);
const selectedDetail = ref<AccountDetailResponse | null>(null);

const importing = computed(() => dashboard.actionKey.value === "import");
const proxyPoolConfigSaving = computed(() => dashboard.actionKey.value === "proxy-pool-sources");

const accountOptions = computed(() =>
  dashboard.details.value.map((detail) => detail.account),
);

const themeOverrides = {
    common: {
        primaryColor: "#c99724",
        primaryColorHover: "#b8891e",
        primaryColorPressed: "#8f6a16",
        borderRadius: "14px",
        fontFamily: "Fira Sans, Segoe UI, sans-serif",
        fontFamilyMono:
            "Fira Code, ui-monospace, SFMono-Regular, Menlo, monospace",
    },
    Button: {
        heightLarge: "46px",
        borderRadiusMedium: "12px",
    },
    Card: {
        borderRadius: "20px",
    },
};

onMounted(async () => {
    await dashboard.refreshDashboard();
    dashboard.checkStartupAccountHealth();
    dashboard.startPolling();
});

function openContext(detail: AccountDetailResponse) {
    selectedDetail.value = detail;
    showContext.value = true;
}

async function submitImport(payload: AccountImportPayload) {
    await dashboard.importAccount(payload);
    showImport.value = false;
}

async function submitProxyPoolSources(content: string) {
    await dashboard.saveProxyPoolSources(content);
    showProxyPoolConfig.value = false;
}

async function updateProduct(accountId: string, productId: string) {
    if (!productId) {
        return;
    }
    await dashboard.updatePreferences(accountId, {
        selected_product_id: productId,
    });
}

async function updateSchedule(
    accountId: string,
    enabled: boolean,
    time: string,
) {
    await dashboard.updatePreferences(accountId, {
        schedule_enabled: enabled,
        scheduled_start_time: time,
    });
}

async function enableAllSchedules() {
    const defaults = dashboard.settings.value;
    const defaultTime = defaults?.scheduled_start_time || "09:59:58";
    await Promise.all(
        dashboard.details.value
            .filter((detail) => !detail.account.schedule_enabled)
            .map((detail) =>
                dashboard.updatePreferences(detail.account.id, {
                    schedule_enabled: true,
                    scheduled_start_time:
                        detail.account.scheduled_start_time || defaultTime,
                }),
            ),
    );
}

function openLogs() {
    showLogs.value = true;
}
</script>

<template>
    <n-config-provider
        :locale="naiveZhCN"
        :date-locale="dateZhCN"
        :theme-overrides="themeOverrides"
    >
        <AppShell
            :health="dashboard.health.value"
            :network-mode-busy="dashboard.networkModeBusy.value"
            @logs="openLogs"
            @refresh="dashboard.refreshDashboard()"
            @import="showImport = true"
            @settings="showSettings = true"
            @update-network-mode="dashboard.updateNetworkMode"
            @configure-proxy-pool="showProxyPoolConfig = true"
        >
            <div class="banner-slot">
                <StatusBanner
                    :banner="dashboard.banner.value"
                    @close="dashboard.clearBanner"
                />
            </div>
            <section class="dashboard-workspace">
                <DashboardStats
                    :accounts-total="dashboard.accountsTotal.value"
                    :running-total="dashboard.runningTotal.value"
                    :pause-requested-total="dashboard.pauseRequestedTotal.value"
                    :qr-total="dashboard.qrTotal.value"
                />
                <AccountTable
                    :details="dashboard.details.value"
                    :loading="dashboard.loading.value"
                    :action-key="dashboard.actionKey.value"
                    @open-context="openContext"
                    @select-product="updateProduct"
                    @update-schedule="updateSchedule"
                    @enable-all-schedules="enableAllSchedules"
                    @delete="dashboard.deleteAccount"
                    @start-stock-monitor="dashboard.startStockMonitor"
                    @stop-stock-monitor="dashboard.stopStockMonitor"
                />
            </section>
        </AppShell>

        <ImportAccountModal
            v-model:show="showImport"
            :loading="importing"
            @submit="submitImport"
        />
        <ProxyPoolConfigModal
            v-model:show="showProxyPoolConfig"
            :loading="proxyPoolConfigSaving"
            @submit="submitProxyPoolSources"
        />
        <AccountContextModal
            v-model:show="showContext"
            :detail="selectedDetail"
        />
        <LogViewer v-model:show="showLogs" :accounts="accountOptions" />
        <GlobalSettingsModal
            v-model:show="showSettings"
            :settings="dashboard.settings.value"
            :loading="dashboard.settingsLoading.value"
            @submit="dashboard.updateSettings"
        />
    </n-config-provider>
</template>
