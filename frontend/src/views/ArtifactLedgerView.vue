<template>
  <div class="page">
    <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px">
      <div>
        <h1 style="margin-bottom: 4px">产物台账</h1>
        <p class="muted" style="margin-top: 0">
          跨 Run 集中查看已挂载产物及其内容指纹（content_sha256）
        </p>
      </div>
      <n-button @click="load">刷新</n-button>
    </div>

    <div class="card">
      <n-data-table :columns="columns" :data="rows" :loading="loading" :bordered="false" />
    </div>
  </div>
</template>

<script setup>
import { h, onMounted, reactive, ref } from 'vue'
import { NButton, NTag, useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import { listArtifacts, verifyArtifact } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const message = useMessage()
const rows = ref([])
const loading = ref(false)
// key: `${run_id}|${uri}` -> 校验结果
const results = reactive({})
const verifying = reactive({})

function keyOf(row) {
  return `${row.run_id}|${row.uri}`
}

const runStatusMap = {
  running: { type: 'info', label: '进行中' },
  completed: { type: 'success', label: '已完成' },
  aborted: { type: 'warning', label: '已中止' },
}

function renderResult(row) {
  const r = results[keyOf(row)]
  if (!r) return h('span', { class: 'muted' }, '未校验')
  if (r.passed) {
    return h(NTag, { type: 'success', size: 'small' }, { default: () => '通过' })
  }
  const failed = (r.checks || []).filter((c) => !c.passed).map((c) => c.detail)
  return h(
    NTag,
    { type: 'error', size: 'small' },
    { default: () => `失败：${failed.join('；') || '校验未通过'}` },
  )
}

const columns = [
  { title: '产物', key: 'name', width: 140 },
  {
    title: 'URI',
    key: 'uri',
    render(row) {
      return h('span', { class: 'mono', style: 'font-size:12px' }, row.uri)
    },
  },
  {
    title: 'content_sha256',
    key: 'content_sha256',
    render(row) {
      return h('span', { class: 'mono muted', style: 'font-size:12px' }, row.content_sha256 || '—')
    },
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
        h(
          'div',
          { style: 'margin-top:4px' },
          [h(NTag, { type: m.type, size: 'small' }, { default: () => m.label })],
        ),
      ])
    },
  },
  {
    title: '校验结果',
    key: 'result',
    width: 200,
    render: renderResult,
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render(row) {
      if (auth.role !== 'researcher') {
        return h('span', { class: 'muted' }, '只读')
      }
      return h(
        NButton,
        {
          size: 'tiny',
          type: 'primary',
          loading: !!verifying[keyOf(row)],
          onClick: () => verify(row),
        },
        { default: () => '校验' },
      )
    },
  },
]

async function verify(row) {
  const k = keyOf(row)
  verifying[k] = true
  try {
    results[k] = await verifyArtifact(row.run_id, row.uri)
    if (results[k].passed) {
      message.success('校验通过')
    } else {
      message.error('校验失败')
    }
  } catch (e) {
    message.error(e.message || '校验失败')
  } finally {
    verifying[k] = false
  }
}

async function load() {
  loading.value = true
  try {
    rows.value = await listArtifacts()
  } catch (e) {
    message.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
