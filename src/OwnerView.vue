<template>
  <div class="min-h-screen bg-gray-50 flex flex-col">
    <header class="bg-gradient-to-r from-green-600 to-emerald-500 text-white shadow-lg">
      <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <svg class="w-8 h-8" fill="currentColor" viewBox="0 0 24 24">
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
          </svg>
          <h1 class="text-xl font-bold">绿能充电桩</h1>
        </div>
        <div class="flex items-center gap-3">
          <span v-if="currentUser" class="text-sm opacity-90">{{ currentUser.phone }}</span>
          <span v-if="currentUser" class="text-xs bg-white/20 px-2 py-0.5 rounded">
            {{ roleText }}
          </span>
          <button @click="showLogin = !showLogin" class="text-sm bg-white/20 hover:bg-white/30 px-3 py-1.5 rounded transition">
            {{ currentUser ? '切换' : '登录' }}
          </button>
          <button v-if="currentUser && currentUser.role !== 'owner'"
                  @click="$emit('goAdmin')"
                  class="text-sm bg-white text-green-700 hover:bg-green-50 px-3 py-1.5 rounded font-medium transition">
            管理后台
          </button>
        </div>
      </div>
    </header>

    <div v-if="showLogin" class="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div class="bg-white rounded-xl shadow-2xl p-6 w-full max-w-sm">
        <h3 class="text-lg font-bold mb-4 text-gray-800">手机号登录</h3>
        <input v-model="loginPhone" type="tel" placeholder="请输入手机号" maxlength="11"
               class="w-full border border-gray-300 rounded-lg px-4 py-2.5 mb-4 focus:ring-2 focus:ring-green-500 focus:border-green-500 outline-none"/>
        <div class="flex gap-2">
          <button @click="doLogin" class="flex-1 bg-green-600 hover:bg-green-700 text-white py-2.5 rounded-lg font-medium transition">
            登录/注册
          </button>
          <button @click="showLogin = false" class="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700 py-2.5 rounded-lg transition">
            取消
          </button>
        </div>
        <p class="text-xs text-gray-400 mt-3">测试账号：13800000001(管理员) 13800000002(运维) 13800000003(车主)</p>
      </div>
    </div>

    <div class="flex-1 flex flex-col lg:flex-row">
      <div class="relative lg:flex-1 h-[50vh] lg:h-auto min-h-[400px] bg-gray-100">
        <div ref="mapContainer" class="absolute inset-0"></div>
        <div class="absolute top-3 left-3 bg-white/95 rounded-lg shadow p-3 text-xs">
          <div class="font-semibold mb-2 text-gray-700">图例</div>
          <div class="flex items-center gap-2 mb-1">
            <span class="w-3 h-3 rounded-full bg-green-500"></span>
            <span class="text-gray-600">充足 (&gt;3空闲)</span>
          </div>
          <div class="flex items-center gap-2 mb-1">
            <span class="w-3 h-3 rounded-full bg-yellow-500"></span>
            <span class="text-gray-600">紧张 (1-2空闲)</span>
          </div>
          <div class="flex items-center gap-2">
            <span class="w-3 h-3 rounded-full bg-gray-400"></span>
            <span class="text-gray-600">已满/故障</span>
          </div>
        </div>

        <div v-if="selectedStation" class="absolute bottom-3 left-3 right-3 lg:right-auto lg:w-96 bg-white rounded-xl shadow-2xl p-4 max-h-[55vh] overflow-y-auto">
          <div class="flex items-start justify-between mb-3">
            <div>
              <h3 class="font-bold text-gray-800 text-lg">{{ selectedStation.name }}</h3>
              <p class="text-sm text-gray-500">{{ selectedStation.address }}</p>
            </div>
            <button @click="selectedStation = null" class="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
          </div>
          <div class="flex gap-2 mb-3 text-xs">
            <span class="bg-green-100 text-green-700 px-2 py-1 rounded">空闲 {{ selectedStation.available }}</span>
            <span class="bg-blue-100 text-blue-700 px-2 py-1 rounded">使用中 {{ chargingCount }}</span>
            <span class="bg-red-100 text-red-700 px-2 py-1 rounded">故障 {{ selectedStation.fault }}</span>
          </div>
          <div class="space-y-2">
            <div v-for="pile in selectedStation.piles" :key="pile.id"
                 class="border rounded-lg p-3 flex items-center justify-between"
                 :class="pileBorderClass(pile.status)">
              <div class="flex-1">
                <div class="flex items-center gap-2">
                  <span class="font-semibold text-gray-800">{{ pile.pile_code }}</span>
                  <span class="text-xs px-1.5 py-0.5 rounded"
                        :class="pile.type === 'fast' ? 'bg-orange-100 text-orange-700' : 'bg-blue-100 text-blue-700'">
                    {{ pile.type === 'fast' ? '快充' : '慢充' }}
                  </span>
                  <span class="text-xs text-gray-500">{{ pile.power }}kW</span>
                </div>
                <div class="text-xs mt-1" :class="pileTextClass(pile.status)">
                  {{ statusText(pile.status) }}
                  <span v-if="pile.fault_code" class="text-red-500"> · {{ pile.fault_code }}</span>
                </div>
              </div>
              <button v-if="pile.status === 'idle'"
                      @click="startCharging(pile)"
                      class="bg-green-600 hover:bg-green-700 text-white text-sm px-4 py-1.5 rounded-lg font-medium transition">
                扫码充电
              </button>
              <button v-else-if="pile.status === 'charging' && currentOrder && currentOrder.pile_code === pile.pile_code"
                      @click="stopCharging()"
                      class="bg-red-500 hover:bg-red-600 text-white text-sm px-4 py-1.5 rounded-lg font-medium transition">
                结束充电
              </button>
              <span v-else class="text-xs text-gray-400 px-3">不可用</span>
            </div>
          </div>
        </div>
      </div>

      <div class="lg:w-96 bg-white border-t lg:border-t-0 lg:border-l border-gray-200 flex flex-col">
        <div class="p-4 border-b border-gray-100">
          <div class="flex gap-2 text-sm">
            <button @click="activeTab = 'charging'"
                    class="flex-1 py-2 rounded-lg font-medium transition"
                    :class="activeTab === 'charging' ? 'bg-green-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'">
              充电中
            </button>
            <button @click="activeTab = 'history'"
                    class="flex-1 py-2 rounded-lg font-medium transition"
                    :class="activeTab === 'history' ? 'bg-green-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'">
              充电记录
            </button>
            <button @click="activeTab = 'scan'"
                    class="flex-1 py-2 rounded-lg font-medium transition"
                    :class="activeTab === 'scan' ? 'bg-green-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'">
              扫码
            </button>
          </div>
        </div>

        <div class="flex-1 overflow-y-auto p-4">
          <div v-if="activeTab === 'charging'">
            <div v-if="currentOrder" class="bg-gradient-to-br from-green-50 to-emerald-50 rounded-xl p-5 border border-green-100">
              <div class="flex items-center justify-between mb-4">
                <h3 class="font-bold text-gray-800">正在充电</h3>
                <span class="text-xs bg-green-600 text-white px-2 py-1 rounded animate-pulse">充电中</span>
              </div>
              <div class="text-xs text-gray-400 mb-3 font-mono">{{ currentOrder.order_no }}</div>
              <div class="grid grid-cols-2 gap-4 mb-4">
                <div>
                  <div class="text-xs text-gray-500 mb-1">桩编号</div>
                  <div class="font-semibold text-gray-800">{{ currentOrder.pile_code }}</div>
                </div>
                <div>
                  <div class="text-xs text-gray-500 mb-1">功率</div>
                  <div class="font-semibold text-gray-800">{{ currentOrder.pile_power }}kW</div>
                </div>
                <div>
                  <div class="text-xs text-gray-500 mb-1">已充电量</div>
                  <div class="font-bold text-2xl text-green-600">{{ currentOrder.energy_kwh }}<span class="text-sm font-normal">度</span></div>
                </div>
                <div>
                  <div class="text-xs text-gray-500 mb-1">已充时长</div>
                  <div class="font-bold text-2xl text-gray-800">{{ formatDuration(currentOrder.duration_seconds) }}</div>
                </div>
              </div>
              <div class="bg-white rounded-lg p-3 mb-4">
                <div class="flex justify-between items-center mb-2">
                  <span class="text-sm text-gray-600">电费</span>
                  <span class="font-medium">¥{{ currentOrder.energy_fee }}</span>
                </div>
                <div class="flex justify-between items-center mb-2">
                  <span class="text-sm text-gray-600">服务费</span>
                  <span class="font-medium">¥{{ currentOrder.service_fee }}</span>
                </div>
                <div class="flex justify-between items-center pt-2 border-t border-gray-100">
                  <span class="text-sm font-semibold text-gray-800">预估费用</span>
                  <span class="font-bold text-xl text-green-600">¥{{ currentOrder.total_fee }}</span>
                </div>
              </div>
              <button @click="stopCharging()" class="w-full bg-red-500 hover:bg-red-600 text-white py-3 rounded-xl font-bold transition">
                结束充电并结算
              </button>
            </div>
            <div v-else class="text-center py-16 text-gray-400">
              <svg class="w-16 h-16 mx-auto mb-3 opacity-40" fill="currentColor" viewBox="0 0 24 24">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
              </svg>
              <p>当前没有正在进行的充电</p>
              <p class="text-sm mt-1">在地图上选择空闲充电桩开始</p>
            </div>
          </div>

          <div v-if="activeTab === 'history'">
            <div v-if="orderHistory.length === 0" class="text-center py-16 text-gray-400">
              <p>暂无充电记录</p>
            </div>
            <div v-else class="space-y-3">
              <div v-for="order in orderHistory" :key="order.id" class="border rounded-xl p-4"
                   :class="order.payment_status === 'pending' && order.end_time ? 'border-yellow-300 bg-yellow-50/40' : ''">
                <div class="flex items-center justify-between mb-2">
                  <div>
                    <span class="font-medium text-gray-800">{{ order.pile_code || order.order_no }}</span>
                    <span class="text-xs text-gray-400 ml-2 font-mono">{{ order.order_no }}</span>
                  </div>
                  <span class="text-xs px-2 py-0.5 rounded"
                        :class="order.payment_status === 'paid' ? 'bg-green-100 text-green-700' :
                                order.payment_status === 'pending' ? 'bg-yellow-100 text-yellow-700' :
                                'bg-gray-100 text-gray-500'">
                    {{ order.payment_status === 'paid' ? '已支付' : order.payment_status === 'pending' ? '待支付' : '已取消' }}
                  </span>
                </div>
                <div class="text-xs text-gray-500 mb-2">
                  {{ order.start_time?.slice(0,16).replace('T',' ') }}
                  <span v-if="order.end_time"> → {{ order.end_time?.slice(0,16).replace('T',' ') }}</span>
                </div>
                <div class="grid grid-cols-3 gap-2 text-xs mb-2 text-gray-500">
                  <div>电量: <span class="text-gray-800 font-medium">{{ order.energy_kwh }}度</span></div>
                  <div>电费: ¥{{ order.energy_fee || 0 }}</div>
                  <div>服务: ¥{{ order.service_fee || 0 }}</div>
                </div>
                <div class="flex items-center justify-between pt-2 border-t border-gray-100">
                  <span class="text-sm text-gray-500">合计</span>
                  <span class="font-bold text-green-600 text-lg">¥{{ order.total_fee }}</span>
                </div>
                <button v-if="order.payment_status === 'pending' && order.end_time"
                        @click="payOrder(order.order_no)"
                        class="w-full mt-3 bg-green-600 hover:bg-green-700 text-white py-2.5 rounded-lg text-sm font-medium transition">
                  立即支付 ¥{{ order.total_fee }}
                </button>
              </div>
            </div>
          </div>

          <div v-if="activeTab === 'scan'" class="text-center py-8">
            <div class="w-48 h-48 mx-auto bg-gray-100 rounded-2xl flex items-center justify-center mb-4 border-2 border-dashed border-gray-300">
              <svg class="w-20 h-20 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                      d="M12 4v1m6 11h2m-6 0h-2v4m0-11v3m0 0h.01M12 12h4.01M16 20h4M4 12h4m12 0h.01M5 8h2a1 1 0 001-1V5a1 1 0 00-1-1H5a1 1 0 00-1 1v2a1 1 0 001 1zm12 0h2a1 1 0 001-1V5a1 1 0 00-1-1h-2a1 1 0 00-1 1v2a1 1 0 001 1zM5 20h2a1 1 0 001-1v-2a1 1 0 00-1-1H5a1 1 0 00-1 1v2a1 1 0 001 1z"/>
              </svg>
            </div>
            <p class="text-gray-600 mb-4">扫描充电桩二维码启动充电</p>
            <div class="max-w-xs mx-auto">
              <div class="flex gap-2">
                <input v-model="manualPileCode" placeholder="或手动输入桩编号如 P0002"
                       class="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500 focus:border-green-500 outline-none"/>
                <button @click="scanStart" class="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition">
                  启动
                </button>
              </div>
              <p class="text-xs text-gray-400 mt-2">提示：可直接在地图上点击充电桩的"扫码充电"</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="settlementModal.show" class="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div class="bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md">
        <div class="text-center mb-5">
          <div class="w-16 h-16 mx-auto bg-green-100 rounded-full flex items-center justify-center mb-3">
            <svg class="w-10 h-10 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
            </svg>
          </div>
          <h3 class="text-xl font-bold text-gray-800">充电已完成</h3>
          <p class="text-sm text-gray-500 mt-1">{{ settlementModal.order_no }}</p>
        </div>
        <div class="bg-gray-50 rounded-xl p-4 mb-5 space-y-3">
          <div class="flex justify-between text-sm">
            <span class="text-gray-500">充电时长</span>
            <span class="font-medium text-gray-800">{{ settlementModal.duration }}</span>
          </div>
          <div class="flex justify-between text-sm">
            <span class="text-gray-500">充电电量</span>
            <span class="font-medium text-gray-800">{{ settlementModal.energy_kwh }} 度</span>
          </div>
          <div class="flex justify-between text-sm">
            <span class="text-gray-500">电费</span>
            <span class="font-medium text-gray-800">¥{{ settlementModal.energy_fee }}</span>
          </div>
          <div class="flex justify-between text-sm">
            <span class="text-gray-500">服务费</span>
            <span class="font-medium text-gray-800">¥{{ settlementModal.service_fee }}</span>
          </div>
          <div class="flex justify-between items-center pt-3 border-t border-gray-200">
            <span class="text-base font-semibold text-gray-800">应付金额</span>
            <span class="font-bold text-2xl text-green-600">¥{{ settlementModal.total_fee }}</span>
          </div>
        </div>
        <div class="flex gap-3">
          <button @click="settlementModal.show = false" class="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700 py-3 rounded-xl font-medium transition">
            稍后支付
          </button>
          <button @click="paySettlement" class="flex-1 bg-green-600 hover:bg-green-700 text-white py-3 rounded-xl font-bold transition">
            立即支付
          </button>
        </div>
      </div>
    </div>

    <div v-if="toastMessage" class="fixed top-20 left-1/2 -translate-x-1/2 z-50">
      <div class="bg-gray-800 text-white px-5 py-2.5 rounded-lg shadow-xl text-sm">
        {{ toastMessage }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

const emit = defineEmits(['goAdmin'])

const API_BASE = 'http://localhost:8000'

const api = axios.create({ baseURL: API_BASE })
api.interceptors.request.use((config) => {
  const user = JSON.parse(localStorage.getItem('cp_user') || 'null')
  if (user?.token) {
    config.headers['X-Token'] = user.token
  }
  return config
})

interface Pile {
  id: number
  pile_code: string
  type: string
  power: number
  status: string
  fault_code: string
}

interface Station {
  id: number
  name: string
  address: string
  latitude: number
  longitude: number
  pile_count: number
  available: number
  fault: number
  piles: Pile[]
}

interface CurrentOrder {
  order_no: string
  pile_code: string
  pile_power: number
  start_time: string
  duration_seconds: number
  energy_kwh: number
  energy_fee: number
  service_fee: number
  total_fee: number
}

const currentUser = ref<any>(null)
const showLogin = ref(false)
const loginPhone = ref('13800000003')
const stations = ref<Station[]>([])
const selectedStation = ref<Station | null>(null)
const activeTab = ref('charging')
const currentOrder = ref<CurrentOrder | null>(null)
const orderHistory = ref<any[]>([])
const manualPileCode = ref('')
const toastMessage = ref('')
const mapContainer = ref<HTMLElement | null>(null)
const settlementModal = ref<{
  show: boolean
  order_no: string
  duration: string
  energy_kwh: number
  energy_fee: number
  service_fee: number
  total_fee: number
}>({ show: false, order_no: '', duration: '', energy_kwh: 0, energy_fee: 0, service_fee: 0, total_fee: 0 })

let map: any = null
let markers: any[] = []
let ws: WebSocket | null = null
let refreshTimer: number | null = null

const roleText = computed(() => {
  const r = currentUser.value?.role
  return r === 'admin' ? '管理员' : r === 'operator' ? '运维人员' : '车主'
})

const chargingCount = computed(() => {
  if (!selectedStation.value) return 0
  return selectedStation.value.piles.filter(p => p.status === 'charging').length
})

const showToast = (msg: string) => {
  toastMessage.value = msg
  setTimeout(() => { toastMessage.value = '' }, 2500)
}

const statusText = (s: string) => ({ idle: '空闲', charging: '充电中', fault: '故障', offline: '离线' }[s] || s)

const pileBorderClass = (s: string) => ({
  'border-green-200 bg-green-50/30': s === 'idle',
  'border-blue-200 bg-blue-50/30': s === 'charging',
  'border-red-200 bg-red-50/30': s === 'fault',
  'border-gray-200 bg-gray-50': s === 'offline',
})

const pileTextClass = (s: string) => ({
  'text-green-600': s === 'idle',
  'text-blue-600': s === 'charging',
  'text-red-600': s === 'fault',
  'text-gray-400': s === 'offline',
})

const formatDuration = (sec: number) => {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  return h > 0 ? `${h}h${String(m).padStart(2,'0')}m` : `${m}m${String(s).padStart(2,'0')}s`
}

const doLogin = async () => {
  if (!loginPhone.value) return
  try {
    const r = await api.post('/api/auth/login', { phone: loginPhone.value })
    currentUser.value = r.data.data
    localStorage.setItem('cp_user', JSON.stringify(r.data.data))
    showLogin.value = false
    await loadOrders()
    showToast('登录成功')
  } catch (e: any) {
    showToast(e.response?.data?.detail || '登录失败')
  }
}

const loadStations = async () => {
  try {
    const r = await api.get('/api/stations')
    stations.value = r.data.data
    renderMarkers()
  } catch (e: any) {
    if (e.response?.status === 401) {
      currentUser.value = null
      localStorage.removeItem('cp_user')
    }
  }
}

const loadOrders = async () => {
  if (!currentUser.value) return
  try {
    const [curr, hist] = await Promise.all([
      api.get('/api/orders/current', { params: { phone: currentUser.value.phone } }),
      api.get('/api/orders', { params: { phone: currentUser.value.phone } }),
    ])
    currentOrder.value = curr.data.data
    orderHistory.value = hist.data.data
  } catch (e: any) {
    if (e.response?.status === 401) {
      currentUser.value = null
      localStorage.removeItem('cp_user')
    }
  }
}

const startCharging = async (pile: Pile) => {
  if (!currentUser.value) {
    showLogin.value = true
    showToast('请先登录')
    return
  }
  try {
    showToast('正在启动充电...')
    const r = await api.post('/api/charging/start', {
      phone: currentUser.value.phone, pile_code: pile.pile_code,
    })
    showToast('充电已启动')
    activeTab.value = 'charging'
    await loadOrders()
    await loadStations()
  } catch (e: any) {
    showToast(e.response?.data?.detail || '启动失败')
  }
}

const stopCharging = async () => {
  if (!currentOrder.value) return
  try {
    showToast('正在结算...')
    const r = await api.post('/api/charging/stop', { order_no: currentOrder.value.order_no })
    const data = r.data.data
    let duration = ''
    if (data.start_time && data.end_time) {
      const sec = Math.floor((new Date(data.end_time).getTime() - new Date(data.start_time).getTime()) / 1000)
      duration = formatDuration(sec)
    }
    settlementModal.value = {
      show: true,
      order_no: data.order_no,
      duration,
      energy_kwh: data.energy_kwh,
      energy_fee: data.energy_fee,
      service_fee: data.service_fee,
      total_fee: data.total_fee,
    }
    currentOrder.value = null
    await loadOrders()
    await loadStations()
  } catch (e: any) {
    showToast(e.response?.data?.detail || '结算失败')
  }
}

const payOrder = async (orderNo: string) => {
  try {
    showToast('支付中...')
    await api.post(`/api/orders/${orderNo}/pay`)
    showToast('支付成功')
    await loadOrders()
  } catch (e: any) {
    showToast(e.response?.data?.detail || '支付失败')
  }
}

const paySettlement = async () => {
  if (!settlementModal.value.order_no) return
  try {
    await api.post(`/api/orders/${settlementModal.value.order_no}/pay`)
    settlementModal.value.show = false
    showToast('支付成功')
    activeTab.value = 'history'
    await loadOrders()
  } catch (e: any) {
    showToast(e.response?.data?.detail || '支付失败')
  }
}

const scanStart = async () => {
  if (!manualPileCode.value) return
  if (!currentUser.value) {
    showLogin.value = true
    return
  }
  try {
    const pr = await api.get(`/api/piles/${manualPileCode.value}`)
    const pile = pr.data.data
    if (pile.status !== 'idle') {
      showToast('该充电桩当前不可用')
      return
    }
    await startCharging(pile)
  } catch (e: any) {
    showToast(e.response?.data?.detail || '桩编号不存在')
  }
}

const renderMarkers = () => {
  if (!map || !(window as any).AMap) return
  markers.forEach(m => m.setMap(null))
  markers = []
  stations.value.forEach(s => {
    let color = '#10b981'
    if (s.available === 0) color = '#9ca3af'
    else if (s.available <= 2) color = '#f59e0b'
    const html = `
      <div style="width:40px;height:40px;background:${color};border-radius:50% 50% 50% 0;transform:rotate(-45deg);
                  border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,0.3);display:flex;align-items:center;justify-content:center;">
        <span style="transform:rotate(45deg);color:#fff;font-weight:bold;font-size:12px;">${s.available}</span>
      </div>`
    const marker = new (window as any).AMap.Marker({
      position: [s.longitude, s.latitude],
      content: html,
      offset: new (window as any).AMap.Pixel(-20, -40),
      title: s.name,
    })
    marker.on('click', () => {
      selectedStation.value = s
    })
    marker.setMap(map)
    markers.push(marker)
  })
}

const initMap = () => {
  if (!mapContainer.value || !(window as any).AMap) {
    setTimeout(initMap, 200)
    return
  }
  map = new (window as any).AMap.Map(mapContainer.value, {
    zoom: 11,
    center: [116.4, 39.9],
    viewMode: '2D',
  })
  renderMarkers()
}

const loadAMap = () => {
  if ((window as any).AMap) {
    initMap()
    return
  }
  const script = document.createElement('script')
  script.src = 'https://webapi.amap.com/maps?v=2.0&key=2a0a87a1b8b0c0a5c1d1e0f1a2b3c4d5'
  script.onload = initMap
  document.head.appendChild(script)
}

const connectWS = () => {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  try {
    ws = new WebSocket(`${proto}//localhost:8000/ws`)
    ws.onmessage = (ev) => {
      const data = JSON.parse(ev.data)
      if (data.type === 'pile_status') {
        const st = stations.value.find(s => s.id === data.station_id)
        if (st) {
          const pile = st.piles.find(p => p.pile_code === data.pile_code)
          if (pile) {
            pile.status = data.status
            pile.fault_code = data.fault_code || ''
            st.available = st.piles.filter(p => p.status === 'idle').length
            st.fault = st.piles.filter(p => p.status === 'fault').length
          }
        }
        renderMarkers()
      } else if (data.type === 'charging_progress') {
        if (currentOrder.value && currentOrder.value.order_no === data.order_no) {
          currentOrder.value.energy_kwh = data.energy_kwh
          currentOrder.value.energy_fee = data.energy_fee ?? currentOrder.value.energy_fee
          currentOrder.value.service_fee = data.service_fee ?? currentOrder.value.service_fee
          currentOrder.value.total_fee = data.total_fee
        }
      }
    }
    ws.onclose = () => setTimeout(connectWS, 3000)
  } catch (e) {
    setTimeout(connectWS, 3000)
  }
}

onMounted(() => {
  const saved = localStorage.getItem('cp_user')
  if (saved) currentUser.value = JSON.parse(saved)
  loadStations()
  loadOrders()
  loadAMap()
  connectWS()
  refreshTimer = window.setInterval(() => {
    if (currentOrder.value) {
      currentOrder.value.duration_seconds += 5
      loadOrders()
    }
  }, 5000)
})

onUnmounted(() => {
  if (ws) ws.close()
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>
