<script setup lang="ts">
import QrPreview from "./QrPreview.vue";
import ScheduleEditor from "./ScheduleEditor.vue";
import { zhCN as copy } from "../locales/zhCN";
import type {
    AccountDetailResponse,
    PaymentTaskRecord,
    ProductOffer,
} from "../types/api";

defineProps<{
    details: AccountDetailResponse[];
    loading: boolean;
    actionKey: string;
}>();

const emit = defineEmits<{
    openContext: [detail: AccountDetailResponse];
    selectProduct: [accountId: string, productId: string];
    updateSchedule: [accountId: string, enabled: boolean, time: string];
    enableAllSchedules: [];
    delete: [accountId: string];
    startStockMonitor: [accountId: string];
    stopStockMonitor: [accountId: string];
}>();

function anyScheduleDisabled(details: AccountDetailResponse[]) {
    return details.some((detail) => !detail.account.schedule_enabled);
}

function latestTask(detail: AccountDetailResponse): PaymentTaskRecord | null {
    return detail.tasks?.[0] || null;
}

function productForTask(detail: AccountDetailResponse): ProductOffer | null {
    const task = latestTask(detail);
    if (!task) {
        return null;
    }
    return (
        detail.session.products?.find(
            (product) => product.product_id === task.product_id,
        ) || null
    );
}

function isScheduleSuccess(detail: AccountDetailResponse) {
    return (
        String(detail.account.last_schedule_status || "").toLowerCase() ===
        "success"
    );
}

function isStockMonitoring(detail: AccountDetailResponse) {
    return Boolean(detail.account.stock_monitor_enabled);
}

function unitLabel(unit: string | undefined) {
    const map: Record<string, string> = {
        month: "月卡",
        quarter: "季卡",
        year: "年卡",
    };
    return map[String(unit || "").toLowerCase()] || unit || "-";
}

function formatPrice(price: string | undefined) {
    const value = parseFloat(String(price || "0"));
    if (Number.isNaN(value) || value === 0) {
        return "-";
    }
    return `¥${value.toFixed(0)}`;
}

function productOptions(detail: AccountDetailResponse) {
    return (detail.session.products || []).map((product) => ({
        label: `${product.product_name} / ${unitLabel(product.unit)} / ${formatPrice(product.sale_price)}`,
        value: product.product_id,
        disabled: Boolean(product.sold_out || product.forbidden),
    }));
}

function selectedProduct(detail: AccountDetailResponse) {
    return detail.session.selected_product_id || null;
}

function displayMode(detail: AccountDetailResponse) {
    return detail.session.purchase_mode === "upgrade"
        ? copy.table.modes.upgrade
        : copy.table.modes.newPurchase;
}

function actionLoading(key: string, accountId: string, actionKey: string) {
    return actionKey === `${key}:${accountId}`;
}
</script>

<template>
    <n-card class="table-panel" :bordered="false">
        <template #header>
            <div class="panel-title">
                <div>
                    <span>{{ copy.table.title }}</span>
                    <small>{{ copy.table.subtitle(details.length) }}</small>
                </div>
                <n-button
                    type="primary"
                    :disabled="!anyScheduleDisabled(details)"
                    @click="emit('enableAllSchedules')"
                >
                    {{ copy.table.enableAllSchedules }}
                </n-button>
            </div>
        </template>

        <n-spin :show="loading" class="table-spin">
            <div
                class="ops-table"
                role="table"
                :aria-label="copy.table.regionLabel"
                tabindex="0"
            >
                <div class="ops-table-head" role="row">
                    <span role="columnheader">{{
                        copy.table.columns.account
                    }}</span>
                    <span role="columnheader">{{
                        copy.table.columns.product
                    }}</span>
                    <span role="columnheader">{{
                        copy.table.columns.status
                    }}</span>
                    <span role="columnheader">{{
                        copy.table.columns.latestQr
                    }}</span>
                    <span role="columnheader">{{
                        copy.table.columns.actions
                    }}</span>
                </div>

                <div v-if="details.length === 0" class="ops-empty">
                    <n-empty :description="copy.table.empty" />
                </div>

                <article
                    v-for="detail in details"
                    :key="detail.account.id"
                    class="ops-row"
                    role="row"
                >
                    <section class="ops-cell account-cell" role="cell">
                        <button
                            class="link-button"
                            type="button"
                            @click="emit('openContext', detail)"
                        >
                            {{ detail.account.label }}
                        </button>
                        <span
                            >{{ displayMode(detail) }} /
                            {{
                                detail.account.browser_impersonate ||
                                copy.table.browserPending
                            }}</span
                        >
                    </section>

                    <section class="ops-cell product-cell" role="cell">
                        <n-select
                            :value="selectedProduct(detail)"
                            :options="productOptions(detail)"
                            :placeholder="copy.table.selectProduct"
                            clearable
                            size="large"
                            @update:value="
                                emit(
                                    'selectProduct',
                                    detail.account.id,
                                    String($event || ''),
                                )
                            "
                        />
                    </section>

                    <section class="ops-cell status-cell" role="cell">
                        <n-tag
                            :type="
                                detail.account.account_status === 'valid'
                                    ? 'success'
                                    : 'warning'
                            "
                            round
                        >
                            {{
                                detail.account.account_status ||
                                copy.table.unchecked
                            }}
                        </n-tag>
                        <small>{{
                            detail.account.last_schedule_status ||
                            detail.account.account_status_message ||
                            copy.table.noRecentEvent
                        }}</small>
                        <small
                            v-if="detail.account.account_status_message"
                            class="account-state-line"
                        >
                            {{ detail.account.account_status_message }}
                        </small>
                        <small
                            v-if="detail.account.stock_monitor_last_message"
                            class="schedule-state-line"
                        >
                            库存:
                            {{ detail.account.stock_monitor_last_message }}
                        </small>
                        <small
                            v-if="
                                isScheduleSuccess(detail) &&
                                latestTask(detail)?.biz_id
                            "
                            class="mono-line"
                        >
                            {{ copy.table.bizId }}:
                            {{ latestTask(detail)?.biz_id }}
                        </small>
                        <small
                            v-if="detail.account.last_upstream_code !== undefined && detail.account.last_upstream_code !== null"
                            class="mono-line"
                            :class="{
                                'upstream-success': detail.account.last_upstream_code === 200,
                                'upstream-error': detail.account.last_upstream_code !== 200,
                            }"
                        >
                            返回码 {{ detail.account.last_upstream_code }}
                            <span v-if="detail.account.last_upstream_message">
                                · {{ detail.account.last_upstream_message }}
                            </span>
                        </small>
                    </section>

                    <section class="ops-cell qr-column" role="cell">
                        <QrPreview
                            :task="latestTask(detail)"
                            :product-unit="productForTask(detail)?.unit"
                        />
                    </section>

                    <section class="ops-cell actions-cell" role="cell">
                        <ScheduleEditor
                            :account-id="detail.account.id"
                            :enabled="Boolean(detail.account.schedule_enabled)"
                            :time="
                                detail.account.scheduled_start_time ||
                                '00:00:00'
                            "
                            @update="
                                (id, enabled, time) =>
                                    emit('updateSchedule', id, enabled, time)
                            "
                        />

                        <n-button
                            secondary
                            :type="isStockMonitoring(detail) ? 'warning' : 'default'"
                            :loading="
                                actionLoading(
                                    'stock',
                                    detail.account.id,
                                    actionKey,
                                )
                            "
                            @click="
                                isStockMonitoring(detail)
                                    ? emit('stopStockMonitor', detail.account.id)
                                    : emit('startStockMonitor', detail.account.id)
                            "
                        >
                            {{
                                isStockMonitoring(detail)
                                    ? copy.table.stopStockMonitor
                                    : copy.table.stockMonitor
                            }}
                        </n-button>

                        <n-popconfirm
                            @positive-click="emit('delete', detail.account.id)"
                        >
                            <template #trigger>
                                <n-button
                                    quaternary
                                    type="error"
                                    :loading="
                                        actionLoading(
                                            'delete',
                                            detail.account.id,
                                            actionKey,
                                        )
                                    "
                                >
                                    {{ copy.table.delete }}
                                </n-button>
                            </template>
                            {{ copy.table.deleteConfirm }}
                        </n-popconfirm>
                    </section>
                </article>
            </div>
        </n-spin>
    </n-card>
</template>
