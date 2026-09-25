import { useState, useEffect } from 'react'
import { Save, Check, Upload, Download, Database, RotateCcw, AlertTriangle, Cloud, HardDrive } from 'lucide-react'
import { getSettings, updateSettings, uploadBranding, exportBackup, importBackup, uploadGDriveCreds, pushGDriveBackup } from '../lib/api'
import { SAVED_FEEDBACK_DELAY } from '../lib/constants'

export default function Settings() {
  const [settings, setSettings] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [uploading, setUploading] = useState({})
  const [exportingBackup, setExportingBackup] = useState(false)
  const [importingBackup, setImportingBackup] = useState(false)
  const [uploadingGDriveCreds, setUploadingGDriveCreds] = useState(false)
  const [pushingGDrive, setPushingGDrive] = useState(false)
  const [backupMessage, setBackupMessage] = useState(null)

  useEffect(() => { load() }, [])

  async function load() {
    try {
      const res = await getSettings()
      setSettings(res.data)
      setError(null)
    } catch (e) {
      console.error(e)
      setError('خطا در بارگذاری تنظیمات')
    }
    setLoading(false)
  }

  async function handleExportBackup() {
    try {
      setExportingBackup(true);
      setBackupMessage(null);
      const res = await exportBackup();
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      link.setAttribute('download', `spaghetti_backup_${timestamp}.db`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      setBackupMessage({ type: 'success', text: 'پشتیبان با موفقیت دانلود شد' });
    } catch (e) {
      console.error(e);
      setBackupMessage({ type: 'error', text: 'خطا در دانلود پشتیبان' });
    } finally {
      setExportingBackup(false);
    }
  }

  async function handleImportBackup(file) {
    if (!file) return;
    if (!confirm('آیا از بازگردانی این فایل پشتیبان اطمینان دارید؟ تمام اطلاعات فعلی جایگزین خواهند شد!')) return;
    try {
      setImportingBackup(true);
      setBackupMessage(null);
      const res = await importBackup(file);
      setBackupMessage({ type: 'success', text: res.data.message || 'پشتیبان با موفقیت بازگردانی شد' });
      setTimeout(() => window.location.reload(), 1500);
    } catch (e) {
      console.error(e);
      setBackupMessage({ type: 'error', text: e.response?.data?.detail || 'خطا در بازگردانی پشتیبان' });
    } finally {
      setImportingBackup(false);
    }
  }

  async function handleUploadGDriveCreds(file) {
    if (!file) return;
    try {
      setUploadingGDriveCreds(true);
      setBackupMessage(null);
      const res = await uploadGDriveCreds(file);
      setBackupMessage({ type: 'success', text: res.data.message + ` (${res.data.client_email})` });
    } catch (e) {
      console.error(e);
      setBackupMessage({ type: 'error', text: e.response?.data?.detail || 'خطا در آپلود فایل اعتبارنامه گوگل' });
    } finally {
      setUploadingGDriveCreds(false);
    }
  }

  async function handlePushGDrive() {
    try {
      setPushingGDrive(true);
      setBackupMessage(null);
      const res = await pushGDriveBackup();
      setBackupMessage({ type: 'success', text: res.data.message || 'پشتیبان به گوگل درایو ارسال شد' });
    } catch (e) {
      console.error(e);
      setBackupMessage({ type: 'error', text: e.response?.data?.detail || 'خطا در ارسال به گوگل درایو' });
    } finally {
      setPushingGDrive(false);
    }
  }

  function handleChange(key, value, isString = false) {
    setSettings(prev => ({
      ...prev,
      [key]: {
        ...prev[key],
        [isString ? 'string_value' : 'value']: isString
          ? value
          : (typeof value === 'number' ? value : (parseFloat(value) || 0))
      }
    }))
  }

  async function handleFileUpload(key, file) {
    if (!file) return
    setUploading(prev => ({ ...prev, [key]: true }))
    try {
      const res = await uploadBranding(key, file)
      const url = res.data.url
      setSettings(prev => ({
        ...prev,
        [key]: { ...prev[key], string_value: url }
      }))
      if (key === 'favicon_url') {
        let link = document.querySelector("link[rel*='icon']")
        if (!link) {
          link = document.createElement('link')
          link.rel = 'icon'
          document.head.appendChild(link)
        }
        link.href = url + '?t=' + Date.now()
      } else if (key === 'logo_url') {
        window.__APP_LOGO_URL = url
      }
    } catch (err) {
      console.error('Upload failed:', err)
      setError('خطا در آپلود فایل: ' + (err.response?.data?.detail || err.message))
    } finally {
      setUploading(prev => ({ ...prev, [key]: false }))
    }
  }

  async function handleSave() {
    setSaving(true)
    const updates = { settings: [] }
    for (const [key, val] of Object.entries(settings)) {
      updates.settings.push({
        key,
        value: val.value ?? 0,
        string_value: val.string_value ?? '',
      })
    }
    try {
      await updateSettings(updates)
      setSaved(true)
      setTimeout(() => setSaved(false), SAVED_FEEDBACK_DELAY)
    } catch (e) {
      console.error(e)
      setError('خطا در ذخیره تنظیمات')
    }
    setSaving(false)
  }

  if (loading) return <div className="p-8 text-center" style={{color:'var(--text-secondary)'}}>در حال بارگذاری...</div>
  if (error) return <div className="p-8 text-center" style={{color:'#ef4444'}}>{error}</div>

  const fields = [
    { key: 'electricity_rate_per_kwh', label: 'تعرفه برق (تومان/کیلووات)', icon: '⚡' },
    { key: 'default_markup_pct', label: 'ضریب قیمت‌گذاری', icon: '💰', hint: '۳ = سه برابر هزینه پایه' },
    { key: 'overhead_fixed_per_job', label: 'هزینه سربار ثابت هر سفارش', icon: '📋' },
    { key: 'coloring_cost_per_hour', label: 'هزینه رنگ‌آمیزی (تومان/ساعت)', icon: '🎨' },
    { key: 'favicon_url', label: 'فاوآیکون (favicon)', icon: '🌐', type: 'url', stringField: true, accept: '.png,.jpg,.jpeg,.svg,.ico,.webp', hint: 'تصویر کوچک نمایش داده‌شده در تب مرورگر' },
    { key: 'logo_url', label: 'لوگو', icon: '🖼️', type: 'url', stringField: true, accept: '.png,.jpg,.jpeg,.svg,.webp', hint: 'لوگوی اصلی برند' },
  ]

  const contactFields = [
    { key: 'contact_brand', label: 'نام برند', icon: '🏷️', stringField: true },
    { key: 'contact_telegram', label: 'تلگرام', icon: '✈️', stringField: true, hint: 'نام کاربری مثل @username' },
    { key: 'contact_whatsapp', label: 'واتس‌اپ', icon: '📱', stringField: true, hint: 'شماره تلفن' },
    { key: 'contact_instagram', label: 'اینستاگرام', icon: '📷', stringField: true, hint: 'نام کاربری مثل @username' },
    { key: 'contact_bale', label: 'بله', icon: '💬', stringField: true, hint: 'نام کاربری مثل @username' },
    { key: 'contact_hours', label: 'ساعات کاری', icon: '🕐', stringField: true, hint: 'مثلاً ۹ تا ۲۱' },
    { key: 'contact_city', label: 'شهر', icon: '📍', stringField: true },
    { key: 'contact_note', label: 'توضیحات', icon: '📝', stringField: true, hint: 'توضیح کوتاه برای صفحه تماس' },
  ]

  const telegramFields = [
    { key: 'telegram_bot_token', label: 'توکن ربات تلگرام (Bot Token)', icon: '🤖', stringField: true, hint: 'توکن دریافت شده از BotFather@ (مثال: 123456789:ABCDefgh...)' },
    { key: 'telegram_admin_chat_id', label: 'چت آیدی ادمین‌ها (Admin Chat IDs)', icon: '👤', stringField: true, hint: 'شناسه‌های تلگرام ادمین‌ها با کاما جدا کنید (مثال: 130945736,987654321)' },
    { key: 'telegram_proxy', label: 'پروکسی SOCKS5 تلگرام (Proxy)', icon: '🌐', stringField: true, hint: 'آدرس پروکسی (پیش‌فرض: socks5://192.168.100.33:10808)' },
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-6 gap-3">
        <h1 className="settings-page-title text-2xl font-bold text-white">تنظیمات</h1>
        <button onClick={handleSave} disabled={saving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-white font-medium transition-all shrink-0"
          style={{background: saved ? '#22c55e' : 'var(--accent)'}}>
          {saved ? <><Check size={18} /> ذخیره شد!</> : <><Save size={18} /> {saving ? 'در حال ذخیره...' : 'ذخیره تنظیمات'}</>}
        </button>
      </div>

      <div className="settings-fields-grid max-w-6xl">
        {fields.map(f => (
          <div
            key={f.key}
            className="settings-field-card rounded-xl p-5"
          >
            <div className="flex items-center gap-3 mb-3">
              <span className="text-2xl">{f.icon}</span>
              <div className="flex-1">
                <label className="font-semibold text-white">{f.label}</label>
                {f.hint && <p className="text-sm mt-0.5 settings-field-hint">{f.hint}</p>}
              </div>
            </div>

            {f.stringField ? (
              <>
                <div className="flex gap-2 items-center">
                  <input
                    type={f.type || 'text'}
                    value={settings[f.key]?.string_value ?? ''}
                    onChange={e => handleChange(f.key, e.target.value, true)}
                    placeholder="https://..."
                    className="flex-1 px-4 py-3 rounded-lg border text-base outline-none transition-colors settings-field-input"
                  />
                  <label className="flex items-center gap-2 px-4 py-3 rounded-lg cursor-pointer transition-colors hover:opacity-80 flex-shrink-0"
                    style={{background:'var(--accent)', color:'white'}}>
                    <Upload size={18} />
                    <span>{uploading[f.key] ? '...' : 'آپلود'}</span>
                    <input
                      type="file"
                      accept={f.accept}
                      className="hidden"
                      onChange={e => handleFileUpload(f.key, e.target.files?.[0])}
                      disabled={uploading[f.key]}
                    />
                  </label>
                </div>
                {settings[f.key]?.string_value && (
                  <div className="mt-3 flex items-center gap-3">
                    <img src={settings[f.key].string_value} alt={f.key}
                      className={f.key === 'favicon_url' ? 'w-8 h-8 object-contain border rounded p-1' : 'h-12 object-contain border rounded px-2 py-1'}
                      style={{borderColor: 'rgba(255,255,255,0.2)', maxWidth: 200}}
                      onError={(e) => { e.target.style.display = 'none' }}
                    />
                    <span className="text-xs settings-field-hint">
                      {f.key === 'favicon_url' ? '✓ فاوآیکون فعلی' : '✓ لوگوی فعلی'}
                    </span>
                  </div>
                )}
              </>
            ) : (
              <input
                type="number"
                step="any"
                value={settings[f.key]?.value ?? ''}
                onChange={e => handleChange(f.key, e.target.value, false)}
                className="w-full px-4 py-3 rounded-lg border text-lg font-medium outline-none transition-colors settings-field-input"
              />
            )}

            {settings[f.key]?.description && (
              <p className="text-xs mt-2 settings-field-hint">{settings[f.key].description}</p>
            )}
          </div>
        ))}
      </div>

      {/* ── Features & Modules Section ── */}
      <h2 className="settings-page-title text-xl font-bold text-white mt-10 mb-4">ماژول‌ها و امکانات سایت</h2>
      <div className="settings-fields-grid max-w-6xl">
        <div className="settings-field-card rounded-xl p-5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">📰</span>
            <div>
              <label className="font-semibold text-white block">فعال‌سازی ماژول وبلاگ</label>
              <p className="text-sm mt-0.5 settings-field-hint">
                نمایش منو و بخش وبلاگ/مقالات در بخش عمومی و مدیریت
              </p>
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={(settings['enable_blog']?.value ?? 0) > 0}
            onClick={() => handleChange('enable_blog', (settings['enable_blog']?.value ?? 0) > 0 ? 0 : 1, false)}
            className={`w-14 h-8 rounded-full p-1 transition-colors duration-200 ease-in-out shrink-0 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500`}
            style={{ background: (settings['enable_blog']?.value ?? 0) > 0 ? 'var(--accent, #FF9A3D)' : '#475569' }}
          >
            <div
              className={`w-6 h-6 rounded-full bg-white shadow-md transform transition-transform duration-200 ease-in-out ${
                (settings['enable_blog']?.value ?? 0) > 0 ? '-translate-x-6' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
      </div>

      {/* ── Contact Info Section ── */}
      <h2 className="settings-page-title text-xl font-bold text-white mt-10 mb-4">اطلاعات تماس</h2>
      <div className="settings-fields-grid max-w-6xl">
        {contactFields.map(f => (
          <div
            key={f.key}
            className="settings-field-card rounded-xl p-5"
          >
            <div className="flex items-center gap-3 mb-3">
              <span className="text-2xl">{f.icon}</span>
              <div className="flex-1">
                <label className="font-semibold text-white">{f.label}</label>
                {f.hint && <p className="text-sm mt-0.5 settings-field-hint">{f.hint}</p>}
              </div>
            </div>
            <input
              type="text"
              value={settings[f.key]?.string_value ?? ''}
              onChange={e => handleChange(f.key, e.target.value, true)}
              className="w-full px-4 py-3 rounded-lg border text-base outline-none transition-colors settings-field-input"
            />
          </div>
        ))}
      </div>

      {/* ── Telegram Admin Bot Section ── */}
      <h2 className="settings-page-title text-xl font-bold text-white mt-10 mb-4">تنظیمات ربات تلگرام و اعلان‌ها</h2>
      <div className="settings-fields-grid max-w-6xl">
        {telegramFields.map(f => (
          <div
            key={f.key}
            className="settings-field-card rounded-xl p-5"
          >
            <div className="flex items-center gap-3 mb-3">
              <span className="text-2xl">{f.icon}</span>
              <div className="flex-1">
                <label className="font-semibold text-white">{f.label}</label>
                {f.hint && <p className="text-sm mt-0.5 settings-field-hint">{f.hint}</p>}
              </div>
            </div>
            <input
              type="text"
              value={settings[f.key]?.string_value ?? ''}
              onChange={e => handleChange(f.key, e.target.value, true)}
              className="w-full px-4 py-3 rounded-lg border text-base outline-none transition-colors settings-field-input"
            />
          </div>
        ))}
      </div>

      {/* ── Backup & Restore Section ── */}
      <h2 className="settings-page-title text-xl font-bold text-white mt-10 mb-4">پشتیبان‌گیری و بازگردانی دیتابیس</h2>
      <div className="settings-fields-grid max-w-6xl">
        <div className="settings-field-card rounded-xl p-6 col-span-full">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-3 rounded-xl bg-amber-500/10 text-amber-400">
                <Database size={24} />
              </div>
              <div>
                <h3 className="font-bold text-white text-base">مدیریت فایل‌های پشتیبان (Backup / Restore)</h3>
                <p className="text-xs text-slate-400 mt-1">
                  دریافت نسخه پشتیبان WAL-safe دیتابیس SQLite یا بازگردانی دیتابیس از فایل .db پشتیبان
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3 shrink-0 w-full sm:w-auto">
              <button
                type="button"
                onClick={handleExportBackup}
                disabled={exportingBackup}
                className="flex-1 sm:flex-initial flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-sm transition-colors disabled:opacity-50"
              >
                <Download size={16} />
                <span>{exportingBackup ? 'در حال دریافت...' : 'دانلود فایل پشتیبان'}</span>
              </button>

              <label className="flex-1 sm:flex-initial flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg border border-slate-700 bg-slate-800 hover:bg-slate-700 text-white font-medium text-sm cursor-pointer transition-colors">
                <RotateCcw size={16} />
                <span>{importingBackup ? 'در حال بازگردانی...' : 'بازگردانی دیتابیس'}</span>
                <input
                  type="file"
                  accept=".db"
                  className="hidden"
                  onChange={e => handleImportBackup(e.target.files?.[0])}
                  disabled={importingBackup}
                />
              </label>
            </div>
          </div>

          {backupMessage && (
            <div
              className={`mt-4 p-3 rounded-lg text-xs font-medium flex items-center gap-2 ${
                backupMessage.type === 'success'
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : 'bg-red-500/10 text-red-400 border border-red-500/20'
              }`}
            >
              <Check size={14} />
              <span>{backupMessage.text}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
