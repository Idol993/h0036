<template>
  <div>
    <OwnerView v-if="view === 'owner'" @goAdmin="view = 'admin'" />
    <AdminView v-else @goHome="view = 'owner'" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import OwnerView from './OwnerView.vue'
import AdminView from './AdminView.vue'

const view = ref<'owner' | 'admin'>('owner')
</script>
