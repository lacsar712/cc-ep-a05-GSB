<template>
  <div class="page">
    <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px">
      <div>
        <h1 style="margin-bottom: 4px">产物台账</h1>
        <p class="muted" style="margin-top: 0">
          跨 Run 汇总已挂载产物的 uri 与 content_sha256 指纹；研究员可执行单条指纹校验。
        </p>
      </div>
      <n-button :loading="loading" @click="load">刷新</n-button>
    </div>

    <div class="card">
      <n-data-table
        :columns="columns"
        :data="rows"
        :loading="loading"
        :bordered="false"
        :row-key="rowKey"
      />
      <p v-if="!loading && !rows.length" class="muted" style="margin-top: 12px">
        暂无已挂载产物。
      </p>
    </div>
  </div>
</template>

<script setup>
import { h, onMounted, reactive, ref } from 'vue'
import { NButton, NPopover, NTag, useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import { listArtifacts, verifyArtifact } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const message = useMessage()
const rows = ref([])
const loading = ref(false)
// key: `${run_id}:${artifact_index}` -> { loading, result }
const verifyState = reactive({})

function rowKey(row) {
  return `${row.run_id}:${row.artifact_index}`
}

function formatTime(v) {
  return v ? new Date(v).toLocaleString() : '—'
}

const runStatusMap = {
  running: { type: 'info', label: '进行中' },
  completed: { type: 'success', label: '已完成' },
  aborted: { type: 'warning', label: '已中止' },
}

function renderVerify(row) {
  const key = rowKey(row)
  const state = verifyState[key]

  if (auth.role !== 'researcher') {
    return h('span', { class: 'muted', style: 'font-size:12px' }, '审计员只读')
  }

  const children = [
    h(
      NButton,
      {
        size: 'tiny',
        type: 'primary',
        loading: !!state?.loading,
        onClick: () => doVerify(row),
      },
      { default: () => (state?.result ? '重新校验' : '校验') },
    ),
  ]

  if (state?.result) {
    const r = state.result
    const tag = h(
      NTag,
      {
        size: 'small',
        type: r.passed ? 'success' : 'error',
        style: 'margin-left:8px',
      },
      { default: () => (r.passed ? '通过' : '失败') },
    )
    const detail = h(
      'div',
      { style: 'max-width:280px' },
      [
        h('div', { style: 'margin-bottom:6px;font-weight:600' }, r.message),
        ...(r.checks || []).map((c) =>
          h('div', { style: 'font-size:12px;margin:2px 0' }, `${c.passed ? '✓' : '✗'} ${c.label}：${c.detail}`),
        ),
      ],
    )
    children.push(
      h(NPopover, { trigger: 'hover', width: 'auto' }, { trigger: () => tag, default: () => detail }),
    )
  }

  return h('div', { style: 'display:flex;align-items:center;gap:4px' }, children)
}

const columns = [
  {
    title: '产物',
    key: 'name',
    render(row) {
      return h('div', [
        h('div', { style: 'font-weight:600' }, row.name || '（未命名）'),
        row.media_type
          ? h('div', { class: 'muted', style: 'font-size:12px' }, row.media_type)
          : null,
      ])
    },
  },
  {
    title: 'URI',
    key: 'uri',
    render(row) {
      return h('span', { class: 'mono', style: 'font-size:12px' }, row.uri)
    },
    ellipsis: { tooltip: true },
  },
  {
    title: 'content_sha256',
    key: 'content_sha256',
    render(row) {
      return h('span', { class: 'mono', style: 'font-size:12px' }, row.content_sha256)
    },
    width: 240,
    ellipsis: { tooltip: true },
  },
  {
    title: '所属 Run',
    key: 'run',
    render(row) {
      const m = runStatusMap[row.run_status] || { type: 'default', label: row.run_status }
      return h('div', [
        h(
          'a',
          {
            href: 'javascript:void(0)',
            onClick: () => router.push(`/runs/${row.run_id}`),
          },
          `${row.project} / ${row.run_name}`,
        ),
        h('div', { style: 'margin-top:2px' }, h(NTag, { type: m.type, size: 'small' }, { default: () => m.label })),
      ])
    },
  },
  {
    title: '挂载时间 / 操作人',
    key: 'attached_at',
    render(row) {
      return h('div', { style: 'font-size:12px' }, [
        h('div', formatTime(row.attached_at)),
        h('div', { class: 'muted' }, row.attached_by || '—'),
      ])
    },
  },
  {
    title: '校验',
    key: 'verify',
    width: 180,
    render: renderVerify,
  },
]

async function load() {
  loading.value = true
  try {
    rows.value = await listArtifacts()
  } catch (e) {
    message.error(e.message || '台账加载失败')
  } finally {
    loading.value = false
  }
}

async function doVerify(row) {
  const key = rowKey(row)
  if (!verifyState[key]) verifyState[key] = reactive({ loading: false, result: null })
  verifyState[key].loading = true
  try {
    verifyState[key].result = await verifyArtifact(row.run_id, row.artifact_index)
  } catch (e) {
    message.error(e.message || '校验请求失败')
  } finally {
    verifyState[key].loading = false
  }
}

onMounted(load)
</script>
