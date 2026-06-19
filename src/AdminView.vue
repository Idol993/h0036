<template>
  <div class="min-h-screen bg-gray-100">
    <header class="bg-white border-b border-gray-200 shadow-sm">
      <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <button @click="$emit('goHome')" class="text-gray-500 hover:text-gray-700">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"/>
            </svg>
          </button>
          <h1 class="text-xl font-bold text-gray-800">充电桩运维管理平台</h1>
        </div>
        <div class="flex items-center gap-2">
          <span v-if="currentUser" class="text-sm text-gray-600">{{ currentUser.phone }}</span>
          <span class="text-xs bg-emerald-100 text-emerald-700 px-2 py-1 rounded font-medium">
            {{ currentUser?.role === 'admin' ? '运营管理员' : '运维人员' }}
          </span>
        </div>
      </div>
    </header>

    <div class="flex border-b border-gray-200 bg-white px-4">
      <button v-for="t in tabs" :key="t.key" @click="activeTab = t.key"
              class="px-4 py-3 text-sm font-medium border-b-2 transition"
              :class="activeTab === t.key ? 'border-emerald-500 text-emerald-600' : 'border-transparent text-gray-500 hover:text-gray-700'">
        {{ t.label }}
      </button>
    </div>

    <div class="max-w-7xl mx-auto p-4">
      <div v-if="activeTab === 'dashboard'" class="space-y-4">
        <div class="bg-white rounded-xl p-4 shadow-sm flex items-center justify-between flex-wrap gap-3">
          <div class="flex items-center gap-2">
            <span class="text-sm text-gray-600">时间范围：</span>
            <div class="flex rounded-lg overflow-hidden border border-gray-200">
              <button v-for="p in periods" :key="p.key" @click="dashboardPeriod = p.key"
                      class="px-4 py-1.5 text-sm transition"
                      :class="dashboardPeriod === p.key ? 'bg-emerald-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'">
                {{ p.label }}
              </button>
            </div>
          </div>
          <div class="text-xs text-gray-400">
            {{ dashboard.range_start?.slice(0,10) }} ~ {{ dashboard.range_end?.slice(0,16).replace('T',' ') }}
          </div>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="bg-white rounded-xl p-5 shadow-sm">
            <div class="text-sm text-gray-500 mb-1">充电桩总数</div>
            <div class="text-3xl font-bold text-gray-800">{{ dashboard.total_piles }}</div>
          </div>
          <div class="bg-white rounded-xl p-5 shadow-sm">
            <div class="text-sm text-gray-500 mb-1">在线率</div>
            <div class="text-3xl font-bold text-green-600">{{ dashboard.online_rate }}%</div>
            <div class="text-xs text-gray-400 mt-1">在线 {{ dashboard.online_piles }} 台</div>
          </div>
          <div class="bg-white rounded-xl p-5 shadow-sm">
            <div class="text-sm text-gray-500 mb-1">故障率</div>
            <div class="text-3xl font-bold" :class="dashboard.fault_rate > 5 ? 'text-red-600' : 'text-yellow-600'">
              {{ dashboard.fault_rate }}%
            </div>
            <div class="text-xs text-gray-400 mt-1">故障 {{ dashboard.fault_count }} 台</div>
          </div>
          <div class="bg-white rounded-xl p-5 shadow-sm cursor-pointer hover:shadow-md transition"
               @click="activeTab = 'fault'">
            <div class="text-sm text-gray-500 mb-1">待处理工单</div>
            <div class="text-3xl font-bold text-orange-600">{{ dashboard.work_order_stats?.pending || 0 }}</div>
            <div class="text-xs text-gray-400 mt-1">
              已解决 {{ dashboard.work_order_stats?.resolved || 0 }} 件
            </div>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div class="md:col-span-1 bg-white rounded-xl p-5 shadow-sm">
            <h3 class="font-semibold text-gray-800 mb-3">{{ periodLabel }}概览</h3>
            <div class="space-y-3">
              <div class="flex justify-between items-center py-2 border-b border-gray-50">
                <span class="text-sm text-gray-600">充电订单</span>
                <span class="font-semibold text-gray-800">{{ dashboard.period_orders }} 单</span>
              </div>
              <div class="flex justify-between items-center py-2 border-b border-gray-50">
                <span class="text-sm text-gray-600">充电量</span>
                <span class="font-semibold text-gray-800">{{ dashboard.period_energy }} 度</span>
              </div>
              <div class="flex justify-between items-center py-2">
                <span class="text-sm text-gray-600">营收</span>
                <span class="font-bold text-green-600 text-lg">¥{{ dashboard.period_revenue }}</span>
              </div>
            </div>
          </div>

          <div class="md:col-span-2 bg-white rounded-xl p-5 shadow-sm">
            <div class="flex items-center justify-between mb-3">
              <h3 class="font-semibold text-gray-800">{{ periodLabel }}充电量&营收趋势</h3>
              <span class="text-xs text-gray-400">单位：度 / 元</span>
            </div>
            <div ref="trendChart" class="h-64"></div>
          </div>
        </div>

        <div v-if="dashboard.fault_warning_stations?.length" class="bg-white rounded-xl p-5 shadow-sm border-l-4 border-red-500">
          <div class="flex items-center gap-2 mb-3">
            <svg class="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 24 24">
              <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
            </svg>
            <h3 class="font-semibold text-gray-800">高故障率站点预警</h3>
            <span class="text-xs text-red-500 bg-red-50 px-2 py-0.5 rounded">
              共 {{ dashboard.fault_warning_stations.length }} 个站点需要关注
            </span>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            <div v-for="s in dashboard.fault_warning_stations" :key="s.id"
                 @click="goToStationFaults(s)"
                 class="bg-red-50 border border-red-200 rounded-lg p-3 cursor-pointer hover:bg-red-100 transition">
              <div class="flex items-start justify-between mb-1">
                <span class="font-medium text-gray-800 text-sm truncate flex-1">{{ s.name }}</span>
                <span class="text-xs bg-red-500 text-white px-2 py-0.5 rounded-full ml-2">
                  故障 {{ s.fault_count }}/{{ s.total }}
                </span>
              </div>
              <div class="flex items-center gap-2 mt-2">
                <div class="flex-1 bg-red-100 rounded-full h-2 overflow-hidden">
                  <div class="h-full bg-red-500 rounded-full" :style="{ width: s.fault_rate + '%' }"></div>
                </div>
                <span class="text-xs font-semibold text-red-600 w-12 text-right">{{ s.fault_rate }}%</span>
              </div>
              <div class="text-xs text-red-500 mt-2 flex items-center gap-1">
                点击查看故障工单
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
                </svg>
              </div>
            </div>
          </div>
        </div>

        <div class="bg-white rounded-xl p-5 shadow-sm">
          <h3 class="font-semibold text-gray-800 mb-4">站点利用率 Top 10</h3>
          <div class="space-y-3">
            <div v-for="(s, idx) in dashboard.top_utilization_stations" :key="s.id" class="flex items-center gap-3">
              <span class="w-6 h-6 rounded-full bg-gray-100 flex items-center justify-center text-xs font-bold"
                    :class="idx < 3 ? 'bg-amber-100 text-amber-700' : 'text-gray-500'">
                {{ idx + 1 }}
              </span>
              <span class="flex-1 text-sm text-gray-700 truncate">{{ s.name }}</span>
              <span class="text-xs text-gray-400 w-24">故障 {{ s.fault_count || 0 }}</span>
              <div class="w-40 bg-gray-100 rounded-full h-2 overflow-hidden">
                <div class="h-full bg-gradient-to-r from-green-400 to-emerald-500 rounded-full transition-all"
                     :style="{ width: s.utilization + '%' }"></div>
              </div>
              <span class="text-sm font-semibold text-gray-700 w-14 text-right">{{ s.utilization }}%</span>
            </div>
            <div v-if="!dashboard.top_utilization_stations?.length" class="text-center py-6 text-gray-400 text-sm">
              暂无数据
            </div>
          </div>
        </div>

        <div v-if="currentUser?.role === 'admin'" class="bg-white rounded-xl p-5 shadow-sm">
          <div class="flex items-center justify-between mb-4">
            <h3 class="font-semibold text-gray-800">计费规则配置</h3>
            <button @click="showAddRule = true" class="text-sm bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 rounded-lg transition">
              + 添加规则
            </button>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="bg-gray-50 text-gray-600">
                  <th class="text-left px-4 py-2 font-medium">时段名称</th>
                  <th class="text-left px-4 py-2 font-medium">起始小时</th>
                  <th class="text-left px-4 py-2 font-medium">结束小时</th>
                  <th class="text-left px-4 py-2 font-medium">单价 (元/度)</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in billingRules" :key="r.id" class="border-t border-gray-100">
                  <td class="px-4 py-2 text-gray-800">{{ r.period_name }}</td>
                  <td class="px-4 py-2 text-gray-600">{{ String(r.start_hour).padStart(2,'0') }}:00</td>
                  <td class="px-4 py-2 text-gray-600">{{ String(r.end_hour).padStart(2,'0') }}:00</td>
                  <td class="px-4 py-2 font-semibold text-green-600">¥{{ r.price_per_kwh }}</td>
                </tr>
                <tr class="border-t border-gray-100 bg-gray-50">
                  <td class="px-4 py-2 text-gray-500">平时（默认）</td>
                  <td class="px-4 py-2 text-gray-500" colspan="2">其他时段</td>
                  <td class="px-4 py-2 font-semibold text-gray-600">¥0.9</td>
                </tr>
                <tr class="border-t border-gray-100 bg-gray-50">
                  <td class="px-4 py-2 text-gray-500">服务费</td>
                  <td class="px-4 py-2 text-gray-500" colspan="2">全时段</td>
                  <td class="px-4 py-2 font-semibold text-gray-600">¥0.8 / 度</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'monitor'" class="flex gap-4 -mx-4">
        <div class="w-72 bg-white border-r border-gray-200 min-h-[calc(100vh-180px)]">
          <div class="p-3 border-b border-gray-100">
            <input v-model="searchKeyword" placeholder="搜索站点..."
                   class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-emerald-500"/>
          </div>
          <div class="overflow-y-auto" style="max-height: calc(100vh - 220px)">
            <div v-for="s in filteredStations" :key="s.id"
                 @click="selectStation(s)"
                 class="px-4 py-3 border-b border-gray-50 cursor-pointer hover:bg-gray-50 transition"
                 :class="selectedStation?.id === s.id ? 'bg-emerald-50' : ''">
              <div class="flex items-start justify-between">
                <div class="flex-1 min-w-0">
                  <div class="font-medium text-gray-800 truncate">{{ s.name }}</div>
                  <div class="text-xs text-gray-500 mt-0.5 truncate">{{ s.address }}</div>
                </div>
                <div v-if="s.fault > 0" class="ml-2 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center font-bold">
                  {{ s.fault }}
                </div>
              </div>
              <div class="flex gap-2 mt-2 text-xs">
                <span class="bg-green-100 text-green-700 px-2 py-0.5 rounded">空闲 {{ s.available }}</span>
                <span class="bg-gray-100 text-gray-600 px-2 py-0.5 rounded">共 {{ s.pile_count }}</span>
              </div>
            </div>
            <div v-if="!filteredStations.length" class="p-6 text-center text-gray-400 text-sm">
              暂无负责的站点
            </div>
          </div>
        </div>

        <div class="flex-1 p-4">
          <div v-if="selectedStation" class="space-y-4">
            <div class="bg-white rounded-xl p-5 shadow-sm">
              <h2 class="text-lg font-bold text-gray-800">{{ selectedStation.name }}</h2>
              <p class="text-sm text-gray-500 mt-1">{{ selectedStation.address }}</p>
              <div class="flex gap-3 mt-4 flex-wrap">
                <button @click="exportStationOrders" :disabled="isExporting"
                        class="text-sm bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-4 py-2 rounded-lg transition disabled:opacity-50">
                  {{ isExporting ? '导出中...' : '导出该站点订单CSV' }}
                </button>
              </div>
            </div>

            <div class="bg-white rounded-xl shadow-sm overflow-hidden">
              <div class="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
                <h3 class="font-semibold text-gray-800">充电桩列表</h3>
                <div class="flex gap-2 text-xs">
                  <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-green-500"></span>空闲</span>
                  <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-blue-500"></span>充电</span>
                  <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-red-500"></span>故障</span>
                  <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-gray-400"></span>离线</span>
                </div>
              </div>
              <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 p-4">
                <div v-for="pile in selectedStation.piles" :key="pile.id"
                     class="border rounded-xl p-4 transition"
                     :class="pileCardClass(pile)">
                  <div class="flex items-start justify-between mb-3">
                    <div>
                      <div class="font-bold text-gray-800 text-lg">{{ pile.pile_code }}</div>
                      <div class="text-xs text-gray-500 mt-0.5">
                        {{ pile.type === 'fast' ? '快充' : '慢充' }} · {{ pile.power }}kW
                      </div>
                    </div>
                    <span class="text-xs px-2 py-1 rounded-full font-medium" :class="statusBadgeClass(pile.status)">
                      {{ statusText(pile.status) }}
                    </span>
                  </div>
                  <div v-if="pile.status === 'fault' || pile.fault_code" class="bg-red-50 border border-red-200 rounded-lg p-2 mb-3">
                    <div class="text-xs text-red-600 font-medium">
                      故障码: {{ pile.fault_code || '未知故障' }}
                    </div>
                  </div>
                  <div class="flex gap-2">
                    <button @click="rebootPile(pile)"
                            class="flex-1 text-xs bg-orange-50 hover:bg-orange-100 text-orange-700 py-2 rounded-lg transition font-medium">
                      远程重启
                    </button>
                    <button @click="markDispatched(pile)"
                            class="flex-1 text-xs bg-blue-50 hover:bg-blue-100 text-blue-700 py-2 rounded-lg transition font-medium">
                      标记派工
                    </button>
                  </div>
                </div>
              </div>
              <div v-if="!selectedStation.piles?.length" class="p-10 text-center text-gray-400 text-sm">
                该站点暂无充电桩
              </div>
            </div>
          </div>

          <div v-else class="text-center py-20 text-gray-400">
            <svg class="w-16 h-16 mx-auto mb-3 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                    d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"/>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                    d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
            <p>请从左侧选择一个站点查看详情</p>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'fault'" class="bg-white rounded-xl shadow-sm">
        <div class="p-4 border-b border-gray-100 flex flex-wrap items-center gap-3">
          <select v-model="woFilter.station_id" @change="loadWorkOrders"
                  class="border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-emerald-500">
            <option value="">全部站点</option>
            <option v-for="s in stations" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
          <select v-model="woFilter.status" @change="loadWorkOrders"
                  class="border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-emerald-500">
            <option value="">全部状态</option>
            <option value="pending">待处理</option>
            <option value="processing">处理中</option>
            <option value="resolved">已解决</option>
            <option value="closed">已关闭</option>
          </select>
          <div class="flex-1"></div>
          <span class="text-sm text-gray-500">
            共 {{ workOrders.length }} 条工单
          </span>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-gray-600">
                <th class="text-left px-4 py-3 font-medium">工单编号</th>
                <th class="text-left px-4 py-3 font-medium">站点</th>
                <th class="text-left px-4 py-3 font-medium">充电桩</th>
                <th class="text-left px-4 py-3 font-medium">故障描述</th>
                <th class="text-left px-4 py-3 font-medium">处理人</th>
                <th class="text-left px-4 py-3 font-medium">创建时间</th>
                <th class="text-center px-4 py-3 font-medium">状态</th>
                <th class="text-right px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="wo in workOrders" :key="wo.id" class="border-t border-gray-100 hover:bg-gray-50">
                <td class="px-4 py-3 font-mono text-xs text-gray-700">{{ wo.order_no }}</td>
                <td class="px-4 py-3 text-gray-700">{{ wo.station_name }}</td>
                <td class="px-4 py-3 text-gray-700">{{ wo.pile_code }}</td>
                <td class="px-4 py-3 text-gray-600 max-w-xs truncate" :title="wo.fault_description">
                  {{ wo.fault_code ? `[${wo.fault_code}] ` : '' }}{{ wo.fault_description || '设备故障' }}
                </td>
                <td class="px-4 py-3 text-gray-500 text-xs">{{ wo.handler_name || '-' }}</td>
                <td class="px-4 py-3 text-gray-500 text-xs">{{ wo.created_at?.slice(0,16).replace('T',' ') }}</td>
                <td class="px-4 py-3 text-center">
                  <span class="text-xs px-2 py-1 rounded-full font-medium"
                        :class="woStatusClass(wo.status)">
                    {{ woStatusText(wo.status) }}
                  </span>
                </td>
                <td class="px-4 py-3 text-right">
                  <button v-if="wo.status === 'pending' || wo.status === 'processing'"
                          @click="openHandleWo(wo)"
                          class="text-xs text-emerald-600 hover:text-emerald-700 font-medium">
                    处理
                  </button>
                  <span v-else class="text-xs text-gray-400">已完结</span>
                </td>
              </tr>
              <tr v-if="!workOrders.length">
                <td colspan="8" class="text-center py-12 text-gray-400">暂无工单数据</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="activeTab === 'revenue'" class="space-y-4">
        <div class="bg-white rounded-xl p-4 shadow-sm flex flex-wrap items-center gap-3">
          <div class="flex items-center gap-2">
            <span class="text-sm text-gray-600">时间范围：</span>
            <div class="flex rounded-lg overflow-hidden border border-gray-200">
              <button v-for="p in revenuePeriods" :key="p.key" @click="revenuePeriod = p.key"
                      class="px-4 py-1.5 text-sm transition"
                      :class="revenuePeriod === p.key ? 'bg-emerald-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'">
                {{ p.label }}
              </button>
            </div>
          </div>
          <div v-if="revenuePeriod === 'custom'" class="flex items-center gap-2">
            <input v-model="revenueDateRange.start" type="date"
                   class="border border-gray-200 rounded-lg px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-500"/>
            <span class="text-gray-400 text-sm">至</span>
            <input v-model="revenueDateRange.end" type="date"
                   class="border border-gray-200 rounded-lg px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-emerald-500"/>
            <button @click="loadRevenueAnalysis"
                    class="bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition">
              查询
            </button>
          </div>
          <div class="flex items-center gap-2 ml-4">
            <span class="text-sm text-gray-600">分组方式：</span>
            <div class="flex rounded-lg overflow-hidden border border-gray-200">
              <button @click="revenueGroupBy = 'station'"
                      class="px-4 py-1.5 text-sm transition"
                      :class="revenueGroupBy === 'station' ? 'bg-emerald-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'">
                按站点
              </button>
              <button @click="revenueGroupBy = 'pile_type'"
                      class="px-4 py-1.5 text-sm transition"
                      :class="revenueGroupBy === 'pile_type' ? 'bg-emerald-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'">
                按桩类型
              </button>
            </div>
          </div>
          <div class="flex-1"></div>
          <div class="text-xs text-gray-400">
            {{ revenueData.range_start?.slice(0,10) }} ~ {{ revenueData.range_end?.slice(0,16).replace('T',' ') }}
          </div>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="bg-white rounded-xl p-5 shadow-sm">
            <div class="text-sm text-gray-500 mb-1">订单总数</div>
            <div class="text-3xl font-bold text-gray-800">{{ revenueData.total_orders }}</div>
          </div>
          <div class="bg-white rounded-xl p-5 shadow-sm">
            <div class="text-sm text-gray-500 mb-1">充电量</div>
            <div class="text-3xl font-bold text-blue-600">{{ revenueData.total_energy }} 度</div>
          </div>
          <div class="bg-white rounded-xl p-5 shadow-sm">
            <div class="text-sm text-gray-500 mb-1">总收入</div>
            <div class="text-3xl font-bold text-green-600">¥{{ revenueData.total_revenue }}</div>
          </div>
          <div class="bg-white rounded-xl p-5 shadow-sm">
            <div class="text-sm text-gray-500 mb-1">客单价</div>
            <div class="text-3xl font-bold text-amber-600">¥{{ revenueData.avg_price }}</div>
          </div>
        </div>

        <div class="bg-white rounded-xl shadow-sm overflow-hidden">
          <div class="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
            <h3 class="font-semibold text-gray-800">
              {{ revenueGroupBy === 'station' ? '站点收入排行' : '桩类型收入分布' }}
            </h3>
            <span class="text-xs text-gray-400">共 {{ revenueData.items?.length || 0 }} 项</span>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="bg-gray-50 text-gray-600">
                  <th class="text-left px-4 py-3 font-medium">排名</th>
                  <th class="text-left px-4 py-3 font-medium">
                    {{ revenueGroupBy === 'station' ? '站点名称' : '桩类型' }}
                  </th>
                  <th class="text-right px-4 py-3 font-medium">订单数</th>
                  <th class="text-right px-4 py-3 font-medium">充电量(度)</th>
                  <th class="text-right px-4 py-3 font-medium">收入(元)</th>
                  <th class="text-right px-4 py-3 font-medium">客单价</th>
                  <th class="text-right px-4 py-3 font-medium">占比</th>
                  <th class="text-center px-4 py-3 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in revenueData.items" :key="item.key" class="border-t border-gray-100 hover:bg-gray-50">
                  <td class="px-4 py-3">
                    <span class="w-6 h-6 rounded-full bg-gray-100 inline-flex items-center justify-center text-xs font-bold"
                          :class="idx < 3 ? 'bg-amber-100 text-amber-700' : 'text-gray-500'">
                      {{ idx + 1 }}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-gray-800 font-medium">{{ item.name }}</td>
                  <td class="px-4 py-3 text-right">{{ item.orders }}</td>
                  <td class="px-4 py-3 text-right text-blue-600">{{ item.energy_kwh }}</td>
                  <td class="px-4 py-3 text-right text-green-600 font-bold">¥{{ item.revenue }}</td>
                  <td class="px-4 py-3 text-right text-gray-500">¥{{ item.avg_price }}</td>
                  <td class="px-4 py-3 text-right">
                    <span class="text-xs text-gray-500">
                      {{ revenueData.total_revenue > 0 ? ((item.revenue / revenueData.total_revenue) * 100).toFixed(1) : 0 }}%
                    </span>
                  </td>
                  <td class="px-4 py-3 text-center">
                    <button v-if="revenueGroupBy === 'station' && item.station_id"
                            @click="openRevenueDetail(item)"
                            class="text-xs text-emerald-600 hover:text-emerald-700 font-medium">
                      查看明细
                    </button>
                    <span v-else class="text-xs text-gray-300">-</span>
                  </td>
                </tr>
                <tr v-if="!revenueData.items?.length">
                  <td colspan="8" class="text-center py-12 text-gray-400">暂无数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'orders'" class="bg-white rounded-xl shadow-sm">
        <div class="p-4 border-b border-gray-100 flex flex-wrap items-center gap-3">
          <input v-model="orderFilter.phone" placeholder="手机号"
                 class="border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-emerald-500 w-36"/>
          <input v-model="orderFilter.start" type="date"
                 class="border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-emerald-500"/>
          <span class="text-gray-400 text-sm">至</span>
          <input v-model="orderFilter.end" type="date"
                 class="border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-emerald-500"/>
          <button @click="loadOrders" class="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition">
            查询
          </button>
          <button @click="exportAllOrders" :disabled="isExporting"
                  class="bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-4 py-2 rounded-lg text-sm transition disabled:opacity-50">
            {{ isExporting ? '导出中...' : '导出CSV' }}
          </button>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-gray-600">
                <th class="text-left px-4 py-3 font-medium">订单号</th>
                <th class="text-left px-4 py-3 font-medium">手机号</th>
                <th class="text-left px-4 py-3 font-medium">充电桩</th>
                <th class="text-left px-4 py-3 font-medium">开始时间</th>
                <th class="text-left px-4 py-3 font-medium">结束时间</th>
                <th class="text-right px-4 py-3 font-medium">电量(度)</th>
                <th class="text-right px-4 py-3 font-medium">费用</th>
                <th class="text-center px-4 py-3 font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="o in orders" :key="o.id" class="border-t border-gray-100 hover:bg-gray-50">
                <td class="px-4 py-3 font-mono text-xs text-gray-700">{{ o.order_no }}</td>
                <td class="px-4 py-3 text-gray-700">{{ o.user_phone }}</td>
                <td class="px-4 py-3 text-gray-700">{{ o.pile_code }}</td>
                <td class="px-4 py-3 text-gray-600">{{ o.start_time?.slice(0,16).replace('T',' ') }}</td>
                <td class="px-4 py-3 text-gray-600">{{ o.end_time?.slice(0,16).replace('T',' ') }}</td>
                <td class="px-4 py-3 text-right font-medium">{{ o.energy_kwh }}</td>
                <td class="px-4 py-3 text-right">
                  <div class="text-green-600 font-bold">¥{{ o.total_fee }}</div>
                  <div class="text-xs text-gray-400">电{{ o.energy_fee }}+服{{ o.service_fee }}</div>
                </td>
                <td class="px-4 py-3 text-center">
                  <span class="text-xs px-2 py-1 rounded-full"
                        :class="o.payment_status === 'paid' ? 'bg-green-100 text-green-700' :
                                o.payment_status === 'pending' ? 'bg-yellow-100 text-yellow-700' :
                                'bg-gray-100 text-gray-500'">
                    {{ o.payment_status === 'paid' ? '已支付' : o.payment_status === 'pending' ? '待支付' : '已取消' }}
                  </span>
                </td>
              </tr>
              <tr v-if="!orders.length">
                <td colspan="8" class="text-center py-12 text-gray-400">暂无订单数据</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-if="showAddRule" class="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div class="bg-white rounded-xl shadow-2xl p-6 w-full max-w-sm">
        <h3 class="text-lg font-bold mb-4 text-gray-800">添加计费规则</h3>
        <div class="space-y-3">
          <div>
            <label class="text-sm text-gray-600 block mb-1">时段名称</label>
            <select v-model="newRule.period_name" class="w-full border border-gray-300 rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-emerald-500">
              <option value="峰时">峰时</option>
              <option value="平时">平时</option>
              <option value="谷时">谷时</option>
            </select>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="text-sm text-gray-600 block mb-1">起始小时</label>
              <input v-model.number="newRule.start_hour" type="number" min="0" max="23"
                     class="w-full border border-gray-300 rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-emerald-500"/>
            </div>
            <div>
              <label class="text-sm text-gray-600 block mb-1">结束小时</label>
              <input v-model.number="newRule.end_hour" type="number" min="0" max="23"
                     class="w-full border border-gray-300 rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-emerald-500"/>
            </div>
          </div>
          <div>
            <label class="text-sm text-gray-600 block mb-1">单价 (元/度)</label>
            <input v-model.number="newRule.price_per_kwh" type="number" step="0.1" min="0"
                   class="w-full border border-gray-300 rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-emerald-500"/>
          </div>
        </div>
        <div class="flex gap-2 mt-5">
          <button @click="submitRule" class="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white py-2.5 rounded-lg font-medium transition">
            确认添加
          </button>
          <button @click="showAddRule = false" class="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700 py-2.5 rounded-lg transition">
            取消
          </button>
        </div>
      </div>
    </div>

    <div v-if="showCreateWo" class="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div class="bg-white rounded-xl shadow-2xl p-6 w-full max-w-md">
        <h3 class="text-lg font-bold mb-4 text-gray-800">创建派工单</h3>
        <div class="space-y-3">
          <div>
            <label class="text-sm text-gray-600 block mb-1">充电桩编号</label>
            <input v-model="createWoForm.pile_code" readonly
                   class="w-full border border-gray-200 rounded-lg px-3 py-2 bg-gray-50 text-gray-500"/>
          </div>
          <div>
            <label class="text-sm text-gray-600 block mb-1">故障码</label>
            <input v-model="createWoForm.fault_code" placeholder="如：E101"
                   class="w-full border border-gray-300 rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-emerald-500"/>
          </div>
          <div>
            <label class="text-sm text-gray-600 block mb-1">故障描述</label>
            <textarea v-model="createWoForm.fault_description" rows="3" placeholder="请描述故障现象..."
                      class="w-full border border-gray-300 rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-emerald-500 resize-none"/>
          </div>
        </div>
        <div class="flex gap-2 mt-5">
          <button @click="submitCreateWo" class="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white py-2.5 rounded-lg font-medium transition">
            创建工单
          </button>
          <button @click="showCreateWo = false" class="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700 py-2.5 rounded-lg transition">
            取消
          </button>
        </div>
      </div>
    </div>

    <div v-if="showHandleWo" class="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div class="bg-white rounded-xl shadow-2xl p-6 w-full max-w-md">
        <h3 class="text-lg font-bold mb-4 text-gray-800">处理工单</h3>
        <div class="space-y-3">
          <div>
            <label class="text-sm text-gray-600 block mb-1">处理结果</label>
            <select v-model="handleWoForm.status" class="w-full border border-gray-300 rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-emerald-500">
              <option value="resolved">已解决</option>
              <option value="processing">处理中</option>
              <option value="closed">已关闭</option>
            </select>
          </div>
          <div>
            <label class="text-sm text-gray-600 block mb-1">处理说明</label>
            <textarea v-model="handleWoForm.result" rows="4" placeholder="请描述处理过程和结果..."
                      class="w-full border border-gray-300 rounded-lg px-3 py-2 outline-none focus:ring-2 focus:ring-emerald-500 resize-none"/>
          </div>
        </div>
        <div class="flex gap-2 mt-5">
          <button @click="submitHandleWo" class="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white py-2.5 rounded-lg font-medium transition">
            提交处理
          </button>
          <button @click="showHandleWo = false" class="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700 py-2.5 rounded-lg transition">
            取消
          </button>
        </div>
      </div>
    </div>

    <div v-if="showRevenueDetail" class="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div class="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[80vh] flex flex-col">
        <div class="p-5 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h3 class="text-lg font-bold text-gray-800">{{ revenueDetailStation?.name }} - 订单明细</h3>
            <p class="text-xs text-gray-500 mt-1">
              共 {{ revenueDetailOrders.length }} 条订单
            </p>
          </div>
          <button @click="showRevenueDetail = false" class="text-gray-400 hover:text-gray-600">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
        <div class="flex-1 overflow-y-auto">
          <table class="w-full text-sm">
            <thead class="bg-gray-50 sticky top-0">
              <tr class="text-gray-600">
                <th class="text-left px-4 py-2 font-medium">订单号</th>
                <th class="text-left px-4 py-2 font-medium">手机号</th>
                <th class="text-left px-4 py-2 font-medium">充电桩</th>
                <th class="text-left px-4 py-2 font-medium">时间</th>
                <th class="text-right px-4 py-2 font-medium">电量</th>
                <th class="text-right px-4 py-2 font-medium">费用</th>
                <th class="text-center px-4 py-2 font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="o in revenueDetailOrders" :key="o.id" class="border-t border-gray-50">
                <td class="px-4 py-2 font-mono text-xs text-gray-700">{{ o.order_no }}</td>
                <td class="px-4 py-2 text-gray-700">{{ o.user_phone }}</td>
                <td class="px-4 py-2 text-gray-600">{{ o.pile_code }}</td>
                <td class="px-4 py-2 text-gray-500 text-xs">{{ o.start_time?.slice(0,16).replace('T',' ') }}</td>
                <td class="px-4 py-2 text-right">{{ o.energy_kwh }}度</td>
                <td class="px-4 py-2 text-right text-green-600 font-medium">¥{{ o.total_fee }}</td>
                <td class="px-4 py-2 text-center">
                  <span class="text-xs px-2 py-0.5 rounded-full"
                        :class="o.payment_status === 'paid' ? 'bg-green-100 text-green-700' :
                                o.payment_status === 'pending' ? 'bg-yellow-100 text-yellow-700' :
                                'bg-gray-100 text-gray-500'">
                    {{ o.payment_status === 'paid' ? '已支付' : o.payment_status === 'pending' ? '待支付' : '已取消' }}
                  </span>
                </td>
              </tr>
              <tr v-if="!revenueDetailOrders.length">
                <td colspan="7" class="text-center py-8 text-gray-400">暂无订单数据</td>
              </tr>
            </tbody>
          </table>
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
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'

const emit = defineEmits(['goHome'])

const API_BASE = 'http://localhost:8000'

const api = axios.create({ baseURL: API_BASE })
api.interceptors.request.use((config) => {
  const user = JSON.parse(localStorage.getItem('cp_user') || 'null')
  if (user?.token) {
    config.headers['X-Token'] = user.token
  }
  return config
})

const tabs = [
  { key: 'dashboard', label: '数据看板' },
  { key: 'fault', label: '故障工单' },
  { key: 'revenue', label: '收入分析' },
  { key: 'monitor', label: '站点监控' },
  { key: 'orders', label: '订单管理' },
]

const periods = [
  { key: 'day', label: '今日' },
  { key: 'week', label: '本周' },
  { key: 'month', label: '本月' },
]

const revenuePeriods = [
  { key: 'day', label: '今日' },
  { key: 'week', label: '本周' },
  { key: 'month', label: '本月' },
  { key: 'custom', label: '自定义' },
]

const currentUser = ref<any>(null)
const activeTab = ref('dashboard')
const dashboardPeriod = ref('day')
const dashboard = ref<any>({
  total_piles: 0, online_piles: 0, online_rate: 0,
  fault_count: 0, fault_rate: 0, charging_count: 0, utilization: 0,
  top_utilization_stations: [], fault_warning_stations: [],
  trend: [], period_orders: 0, period_energy: 0, period_revenue: 0,
  range_start: '', range_end: '',
})
const stations = ref<any[]>([])
const selectedStation = ref<any>(null)
const searchKeyword = ref('')
const orders = ref<any[]>([])
const orderFilter = ref({ phone: '', start: '', end: '' })
const billingRules = ref<any[]>([])
const showAddRule = ref(false)
const newRule = ref({ period_name: '峰时', start_hour: 0, end_hour: 0, price_per_kwh: 0 })
const toastMessage = ref('')
const trendChart = ref<HTMLElement | null>(null)
const isExporting = ref(false)
const workOrders = ref<any[]>([])
const woFilter = ref({ station_id: '', status: '' })
const showCreateWo = ref(false)
const createWoForm = ref({ pile_code: '', fault_code: '', fault_description: '' })
const showHandleWo = ref(false)
const handleWoForm = ref({ result: '', status: 'resolved' })
const selectedWoId = ref<number | null>(null)
const revenuePeriod = ref('day')
const revenueGroupBy = ref('station')
const revenueDateRange = ref({ start: '', end: '' })
const revenueData = ref<any>({ total_orders: 0, total_energy: 0, total_revenue: 0, avg_price: 0, items: [] })
const showRevenueDetail = ref(false)
const revenueDetailStation = ref<any>(null)
const revenueDetailOrders = ref<any[]>([])

let chart: any = null
let ws: WebSocket | null = null
let refreshTimer: ReturnType<typeof setInterval> | null = null

const periodLabel = computed(() => periods.find(p => p.key === dashboardPeriod.value)?.label || '今日')

const showToast = (msg: string) => {
  toastMessage.value = msg
  setTimeout(() => { toastMessage.value = '' }, 2500)
}

const statusText = (s: string) => ({ idle: '空闲', charging: '充电中', fault: '故障', offline: '离线' })[s] || s

const statusBadgeClass = (s: string) => ({
  'bg-green-100 text-green-700': s === 'idle',
  'bg-blue-100 text-blue-700': s === 'charging',
  'bg-red-100 text-red-700': s === 'fault',
  'bg-gray-100 text-gray-500': s === 'offline',
})

const pileCardClass = (pile: any) => ({
  'border-green-200': pile.status === 'idle',
  'border-blue-200': pile.status === 'charging',
  'border-red-300 bg-red-50/30': pile.status === 'fault',
  'border-gray-200': pile.status === 'offline',
})

const filteredStations = computed(() => {
  if (!searchKeyword.value) return stations.value
  const kw = searchKeyword.value.toLowerCase()
  return stations.value.filter(s =>
    s.name.toLowerCase().includes(kw) || s.address.toLowerCase().includes(kw)
  )
})

watch(dashboardPeriod, () => {
  loadDashboard()
})

watch(activeTab, (tab) => {
  if (tab === 'fault') loadWorkOrders()
  if (tab === 'revenue') loadRevenueAnalysis()
  if (tab === 'orders') loadOrders()
  if (tab === 'dashboard') loadDashboard()
})

watch(revenuePeriod, () => {
  loadRevenueAnalysis()
})

watch(revenueGroupBy, () => {
  loadRevenueAnalysis()
})

const loadDashboard = async () => {
  try {
    const r = await api.get('/api/admin/dashboard', { params: { period: dashboardPeriod.value } })
    dashboard.value = r.data.data
    renderTrendChart()
  } catch (e: any) {
    if (e.response?.status === 401 || e.response?.status === 403) {
      showToast(e.response?.data?.detail || '无权限访问')
      emit('goHome')
    }
  }
}

const loadStations = async () => {
  try {
    const r = await api.get('/api/stations')
    stations.value = r.data.data
    if (selectedStation.value) {
      const updated = stations.value.find(s => s.id === selectedStation.value.id)
      if (updated) selectedStation.value = updated
    }
  } catch (e: any) {
    if (e.response?.status === 401) {
      currentUser.value = null
      localStorage.removeItem('cp_user')
    }
  }
}

const loadOrders = async () => {
  try {
    const params: any = {}
    if (orderFilter.value.phone) params.phone = orderFilter.value.phone
    if (orderFilter.value.start) params.start_date = orderFilter.value.start + 'T00:00:00'
    if (orderFilter.value.end) params.end_date = orderFilter.value.end + 'T23:59:59'
    const r = await api.get('/api/orders', { params })
    orders.value = r.data.data
  } catch (e: any) {
    if (e.response?.status === 401) {
      currentUser.value = null
      localStorage.removeItem('cp_user')
    }
  }
}

const loadBillingRules = async () => {
  if (currentUser.value?.role !== 'admin') return
  try {
    const r = await api.get('/api/billing/rules')
    billingRules.value = r.data.data
  } catch (e: any) {
    if (e.response?.status !== 403) console.error(e)
  }
}

const selectStation = (s: any) => {
  selectedStation.value = s
}

const goToStationFaults = (s: any) => {
  woFilter.value.station_id = String(s.id)
  activeTab.value = 'fault'
}

const rebootPile = async (pile: any) => {
  if (!confirm(`确定要远程重启充电桩 ${pile.pile_code} 吗？`)) return
  try {
    await api.post('/api/piles/command', { pile_code: pile.pile_code, command: 'reboot' })
    showToast('重启指令已下发')
    await loadStations()
  } catch (e: any) {
    showToast(e.response?.data?.detail || '操作失败')
  }
}

const markDispatched = (pile: any) => {
  openCreateWo(pile)
}

const _downloadCsv = async (params: any, filename: string) => {
  isExporting.value = true
  try {
    const user = JSON.parse(localStorage.getItem('cp_user') || 'null')
    const headers: any = {}
    if (user?.token) headers['X-Token'] = user.token
    const resp = await axios.get(`${API_BASE}/api/orders/export`, {
      params, headers, responseType: 'blob',
    })
    const contentType = resp.headers['content-type'] || ''
    if (contentType.includes('application/json')) {
      const text = await new Response(resp.data).text()
      const json = JSON.parse(text)
      if (json.empty) {
        showToast(json.message || '该条件下没有可导出的订单')
        return
      }
    }
    const url = window.URL.createObjectURL(new Blob([resp.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
    showToast('导出成功')
  } catch (e: any) {
    if (e.response?.data) {
      try {
        const reader = new FileReader()
        reader.onload = () => {
          try {
            const json = JSON.parse(reader.result as string)
            showToast(json.message || json.detail || '导出失败')
          } catch {
            showToast('导出失败')
          }
        }
        reader.readAsText(e.response.data)
        return
      } catch {}
    }
    showToast(e.message || '导出失败')
  } finally {
    isExporting.value = false
  }
}

const exportAllOrders = () => {
  const params: any = {}
  if (orderFilter.value.start) params.start_date = orderFilter.value.start + 'T00:00:00'
  if (orderFilter.value.end) params.end_date = orderFilter.value.end + 'T23:59:59'
  const fname = `orders_${Date.now()}.csv`
  _downloadCsv(params, fname)
}

const exportStationOrders = () => {
  if (!selectedStation.value) return
  const fname = `${selectedStation.value.name}_orders_${Date.now()}.csv`
  _downloadCsv({ station_id: selectedStation.value.id }, fname)
}

const submitRule = async () => {
  try {
    await api.post('/api/billing/rules', newRule.value)
    showAddRule.value = false
    newRule.value = { period_name: '峰时', start_hour: 0, end_hour: 0, price_per_kwh: 0 }
    await loadBillingRules()
    showToast('规则添加成功')
  } catch (e: any) {
    showToast(e.response?.data?.detail || '添加失败')
  }
}

const loadWorkOrders = async () => {
  try {
    const params: any = {}
    if (woFilter.value.station_id) params.station_id = woFilter.value.station_id
    if (woFilter.value.status) params.status = woFilter.value.status
    const r = await api.get('/api/work-orders', { params })
    workOrders.value = r.data.data
  } catch (e: any) {
    showToast(e.response?.data?.detail || '加载失败')
  }
}

const openCreateWo = (pile: any) => {
  createWoForm.value = { pile_code: pile.pile_code, fault_code: pile.fault_code || '', fault_description: '' }
  showCreateWo.value = true
}

const submitCreateWo = async () => {
  try {
    await api.post('/api/work-orders', createWoForm.value)
    showCreateWo.value = false
    createWoForm.value = { pile_code: '', fault_code: '', fault_description: '' }
    await loadWorkOrders()
    await loadDashboard()
    showToast('工单创建成功')
  } catch (e: any) {
    showToast(e.response?.data?.detail || '创建失败')
  }
}

const openHandleWo = (wo: any) => {
  selectedWoId.value = wo.id
  handleWoForm.value = { result: '', status: 'resolved' }
  showHandleWo.value = true
}

const submitHandleWo = async () => {
  if (!selectedWoId.value) return
  try {
    await api.post(`/api/work-orders/${selectedWoId.value}/handle`, handleWoForm.value)
    showHandleWo.value = false
    selectedWoId.value = null
    await loadWorkOrders()
    await loadDashboard()
    showToast('工单处理完成')
  } catch (e: any) {
    showToast(e.response?.data?.detail || '处理失败')
  }
}

const woStatusText = (s: string) => ({
  pending: '待处理', processing: '处理中', resolved: '已解决', closed: '已关闭'
})[s] || s

const woStatusClass = (s: string) => ({
  'bg-yellow-100 text-yellow-700': s === 'pending',
  'bg-blue-100 text-blue-700': s === 'processing',
  'bg-green-100 text-green-700': s === 'resolved',
  'bg-gray-100 text-gray-500': s === 'closed',
})

const loadRevenueAnalysis = async () => {
  try {
    const params: any = {
      period: revenuePeriod.value,
      group_by: revenueGroupBy.value,
    }
    if (revenuePeriod.value === 'custom') {
      if (revenueDateRange.value.start) params.start_date = revenueDateRange.value.start + 'T00:00:00'
      if (revenueDateRange.value.end) params.end_date = revenueDateRange.value.end + 'T23:59:59'
    }
    const r = await api.get('/api/revenue/analysis', { params })
    revenueData.value = r.data.data
  } catch (e: any) {
    showToast(e.response?.data?.detail || '加载失败')
  }
}

const openRevenueDetail = async (item: any) => {
  if (!item.station_id) return
  revenueDetailStation.value = item
  try {
    const params: any = { station_id: item.station_id, exclude_cancelled: true }
    if (revenuePeriod.value === 'custom') {
      if (revenueDateRange.value.start) params.start_date = revenueDateRange.value.start + 'T00:00:00'
      if (revenueDateRange.value.end) params.end_date = revenueDateRange.value.end + 'T23:59:59'
    } else {
      const rng = revenueData.value
      if (rng.range_start) params.start_date = rng.range_start
      if (rng.range_end) params.end_date = rng.range_end
    }
    const r = await api.get('/api/orders', { params })
    revenueDetailOrders.value = r.data.data
    showRevenueDetail.value = true
  } catch (e: any) {
    showToast(e.response?.data?.detail || '加载失败')
  }
}

const renderTrendChart = () => {
  if (!trendChart.value) return
  if (!chart) chart = echarts.init(trendChart.value)
  const data = dashboard.value.trend || []
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['充电量(度)', '营收(元)'], right: 0 },
    grid: { left: 40, right: 50, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: data.map((d: any) => d.label), axisLabel: { fontSize: 11 } },
    yAxis: [
      { type: 'value', name: '度', position: 'left' },
      { type: 'value', name: '元', position: 'right' },
    ],
    series: [
      { name: '充电量(度)', type: 'bar', data: data.map((d: any) => d.energy_kwh), itemStyle: { color: '#10b981' }, yAxisIndex: 0 },
      { name: '营收(元)', type: 'line', data: data.map((d: any) => d.revenue), itemStyle: { color: '#f59e0b' }, smooth: true, yAxisIndex: 1 },
    ],
  })
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
          const pile = st.piles.find((p: any) => p.pile_code === data.pile_code)
          if (pile) {
            const oldStatus = pile.status
            pile.status = data.status
            pile.fault_code = data.fault_code || ''
            st.available = st.piles.filter((p: any) => p.status === 'idle').length
            st.fault = st.piles.filter((p: any) => p.status === 'fault').length
            if (oldStatus !== 'idle' && (data.status === 'idle' || data.status === 'charging')) {
              loadDashboard()
              if (activeTab.value === 'fault') loadWorkOrders()
            }
          }
        }
        if (selectedStation.value && selectedStation.value.id === data.station_id) {
          selectedStation.value = { ...selectedStation.value }
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
  if (!currentUser.value || currentUser.value.role === 'owner') {
    showToast('请使用运维或管理员账号登录')
    emit('goHome')
    return
  }
  loadDashboard()
  loadStations()
  loadOrders()
  loadBillingRules()
  connectWS()
  window.addEventListener('resize', renderTrendChart)
  refreshTimer = setInterval(() => {
    loadDashboard()
    if (activeTab.value === 'fault') loadWorkOrders()
  }, 30000)
})

onUnmounted(() => {
  if (ws) ws.close()
  if (chart) chart.dispose()
  if (refreshTimer) clearInterval(refreshTimer)
  window.removeEventListener('resize', renderTrendChart)
})
</script>
