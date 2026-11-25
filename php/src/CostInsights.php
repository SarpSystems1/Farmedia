<?php
/**
 * Indicative input costs and cost-saving tips, by country. Port of services/cost_insights.py.
 *
 * The benchmark ranges are Turkish planning figures in TRY per decare, per season. They are not
 * live prices and are shown only for Turkey. For other countries no figures are invented.
 * Review the TRY ranges against current Turkish dealer prices before relying on them.
 */

declare(strict_types=1);

namespace Farmedia;

final class CostInsights
{
    private const BENCHMARK_COUNTRY = 'TR';

    private const ESTIMATES = [
        ['id' => 'seed', 'icon' => '🌾', 'min' => 400, 'max' => 700,
            'label' => ['tr' => 'Tohum', 'en' => 'Seed']],
        ['id' => 'fertilizer', 'icon' => '🧪', 'min' => 150, 'max' => 350,
            'label' => ['tr' => 'Gübre (NPK, üre)', 'en' => 'Fertilizer (NPK, urea)']],
        ['id' => 'crop_protection', 'icon' => '🛡️', 'min' => 100, 'max' => 300,
            'label' => ['tr' => 'İlaçlama (fungisit, insektisit)', 'en' => 'Crop protection (fungicide, insecticide)']],
        ['id' => 'irrigation', 'icon' => '💧', 'min' => 80, 'max' => 250,
            'label' => ['tr' => 'Sulama (su, elektrik, mazot)', 'en' => 'Irrigation (water, power, diesel)']],
        ['id' => 'machinery', 'icon' => '🚜', 'min' => 300, 'max' => 700,
            'label' => ['tr' => 'Makine hizmeti (sürüm, ekim, hasat)', 'en' => 'Machinery services (tillage, sowing, harvest)']],
    ];

    /** scope "any" applies everywhere; "tr" refers to Turkish institutions and shows for Turkey only. */
    private const TIPS = [
        ['id' => 'coop', 'icon' => '🤝', 'scope' => 'any',
            'tr' => ['Ortak alım yapın', 'Kooperatifler veya komşularla toplu alım, birim fiyatı düşürür. Tohum ve gübrede toplu alım en belirgin tasarrufu sağlar.'],
            'en' => ['Buy together', 'Bulk orders through a cooperative or with neighbours lower the unit price. Seed and fertiliser show the clearest savings.']],
        ['id' => 'soil', 'icon' => '🧫', 'scope' => 'any',
            'tr' => ['Gübreden önce toprak analizi', 'Toprak analizi, neyin eksik olduğunu gösterir. Gereksiz gübre almak en sık görülen gider kalemidir. Bir toprak analiz laboratuvarına veya ziraat danışmanına başvurun.'],
            'en' => ['Test soil before fertilising', 'A soil test shows what is actually missing. Unneeded fertiliser is one of the most common avoidable costs. A soil lab or agronomy adviser can test it.']],
        ['id' => 'seed_rate', 'icon' => '🌱', 'scope' => 'any',
            'tr' => ['Önerilen ekim sıklığına uyun', 'Fazla tohum sarf etmek parayı boşa harcar. Sertifikalı tohum daha pahalıdır ama çimlenme oranı yüksek olduğu için yeniden ekim riskini azaltır.'],
            'en' => ['Stick to the recommended seeding rate', 'Over-seeding wastes money. Certified seed costs more but germinates reliably, which reduces the risk of re-sowing.']],
        ['id' => 'share_machines', 'icon' => '🚜', 'scope' => 'any',
            'tr' => ['Makineyi kiralayın veya paylaşın', 'Her işe kendi makineniz gerekmez. Makine kooperatifleri ve hizmet veren çiftçiler dekar başına ücret karşılığı çalışır; yılda az kullanılan makineler için genelde daha ucuzdur.'],
            'en' => ['Rent or share machinery', 'You rarely need to own every machine. Machinery cooperatives and custom operators charge per unit area, which is usually cheaper for equipment used only a few times a year.']],
        ['id' => 'spray_window', 'icon' => '🧪', 'scope' => 'any',
            'tr' => ['İlacı doğru pencerede uygulayın', 'Rüzgârsız ve yağmursuz bir pencerede ilaçlama, ilacın boşa gitmesini ve tekrar uygulamayı önler. Panodaki \'ilaçlama için uygun pencere\' uyarısını takip edin.'],
            'en' => ['Spray in the right window', 'Spraying in calm, dry weather avoids drift and repeat passes. Follow the \'good spraying window\' alert on the dashboard.']],
        ['id' => 'water', 'icon' => '💧', 'scope' => 'any',
            'tr' => ['Suyu verimli kullanın', 'Malç, damla sulama ve sabah erken ya da akşam sulama, su ve pompa yakıtını azaltır. Yağış beklenen günlerde sulamayı erteleyin.'],
            'en' => ['Use water efficiently', 'Mulch, drip irrigation and watering early morning or evening cut both water and pump fuel. Postpone irrigation when rain is forecast.']],
        ['id' => 'subsidies', 'icon' => '📋', 'scope' => 'tr',
            'tr' => ['Destek programlarını kontrol edin', 'Mazot, gübre ve sigorta destekleri yıllara göre değişir. Güncel programlar için il tarım müdürlüğüne veya kooperatifinize danışın.'],
            'en' => ['Check support programmes', 'Diesel, fertiliser and insurance support changes from year to year. Ask your provincial directorate or cooperative for current programmes.']],
        ['id' => 'compare', 'icon' => '🏷️', 'scope' => 'any',
            'tr' => ['Fiyatları karşılaştırın, sezon dışında alın', 'En az iki-üç bayiden fiyat alın. Girdiler çoğu zaman yoğun sezon öncesinde daha ucuzdur; kuru ve serin bir yerde saklayın.'],
            'en' => ['Compare prices and buy off-peak', 'Get quotes from two or three dealers. Inputs are often cheaper before the peak season; store them dry and cool.']],
    ];

    /**
     * @return array<string, mixed>
     */
    public static function build(string $lang, ?float $farmSize, ?string $countryCode): array
    {
        $lang = $lang === 'tr' ? 'tr' : 'en';
        $hasBenchmarks = $countryCode === self::BENCHMARK_COUNTRY;

        $tips = [];
        foreach (self::TIPS as $tip) {
            if ($tip['scope'] === 'any' || $hasBenchmarks) {
                $tips[] = ['id' => $tip['id'], 'icon' => $tip['icon'], 'title' => $tip[$lang][0], 'text' => $tip[$lang][1]];
            }
        }
        $currency = Regions::currency($countryCode);

        if (!$hasBenchmarks) {
            // No figures for this country. The currency is still shown, so prices are read correctly.
            return ['benchmarks' => false, 'currency' => $currency, 'estimates' => [], 'total' => null, 'tips' => $tips];
        }

        $estimates = [];
        $totalMin = 0.0;
        $totalMax = 0.0;
        foreach (self::ESTIMATES as $e) {
            $row = [
                'id' => $e['id'],
                'icon' => $e['icon'],
                'label' => $e['label'][$lang],
                'min_per_decare' => $e['min'],
                'max_per_decare' => $e['max'],
            ];
            if ($farmSize) {
                $row['total_min'] = (int) round($e['min'] * $farmSize);
                $row['total_max'] = (int) round($e['max'] * $farmSize);
                $totalMin += $row['total_min'];
                $totalMax += $row['total_max'];
            }
            $estimates[] = $row;
        }

        return [
            'benchmarks' => true,
            'currency' => $currency ?? ['code' => 'TRY', 'symbol' => '₺', 'locale' => 'tr-TR'],
            'estimates' => $estimates,
            'total' => $farmSize ? ['min' => (int) round($totalMin), 'max' => (int) round($totalMax)] : null,
            'tips' => $tips,
        ];
    }
}
