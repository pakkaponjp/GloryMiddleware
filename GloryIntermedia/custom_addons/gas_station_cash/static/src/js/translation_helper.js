/** @odoo-module **/

// This object holds all the hardcoded translations for the secondary languages.
// The keys are the primary English text (which must match the text in the XML template).
const secondaryTranslations = {
    'Deposit Oil Sales': {
        'th_TH': 'ฝากเงินยอดขายน้ำมัน',
        'en_US': 'Deposit Oil Sales',
        'lo_LA': 'ຝາກເງິນຍອດຂາຍນໍ້າມັນ',      // Lao
        'my_MM': 'ရေနံအရောင်းသွင်းငွေ',        // Myanmar
        'km_KH': 'ដាក់ប្រាក់ការលក់ប្រេងឥន្ធនៈ' // Cambodian
    },
    'Deposit Engine Oil Sales': {
        'th_TH': 'ฝากเงินยอดขายน้ำมันเครื่อง',
        'en_US': 'Deposit Engine Oil Sales',
        'lo_LA': 'ຝາກເງິນຍອດຂາຍນໍ້າມັນເຄື່ອງ',  // Lao
        'my_MM': 'ရေနံအရောင်းသွင်းငွေ',        // Myanmar
        'km_KH': 'ដាក់ប្រាក់ការលក់ប្រេងម៉ាស៊ីន' // Cambodian
    },
    'Exchange Notes and Coins': {
        'th_TH': 'แลกธนบัตรและเหรียญ',
        'en_US': 'Exchange Notes and Coins',
        'lo_LA': 'ແລກປ່ຽນທະນະບັດ ແລະ ເຫรียญ', // Lao
        'my_MM': 'ငွေစက္ကူနှင့်ငွေကြေးလဲလှယ်ခြင်း', // Myanmar
        'km_KH': 'ប្តូរក្រដាសប្រាក់ និងកាក់'      // Cambodian
    },
    'Deposit Coffee Shop Sales': {
        'th_TH': 'ฝากเงินยอดขายร้านกาแฟ',
        'en_US': 'Deposit Coffee Shop Sales',
        'lo_LA': 'ຝາກເງິນຍອດຂາຍຮ້ານກາເຟ',      // Lao
        'my_MM': 'ကော်ဖီဆိုင်အရောင်းသွင်းငွေ', // Myanmar
        'km_KH': 'ដាក់ប្រាក់ការលក់របស់ហាងកាហ្វេ' // Cambodian
    },
    'Deposit Convenient Store Sales': {
        'th_TH': 'ฝากเงินยอดขายร้านสะดวกซื้อ',
        'en_US': 'Deposit Convenient Store Sales',
        'lo_LA': 'ຝາກເງິນຍອດຂາຍຮ້ານສະດວກຊື້',          // Lao
        'my_MM': 'ဆိုင်အဆင်ပြေ အရောင်းသွင်းငွေ', // Myanmar
        'km_KH': 'ដាក់ប្រាក់ការលក់របស់ហាងទំនេីប'       // Cambodian
    },
    'Deposit Rental': {
        'th_TH': 'ฝากเงินค่าเช่า',
        'en_US': 'Deposit Rental',
        'lo_LA': 'ຝາກເງິນຄ່າເຊົ່າ',   // Lao
        'my_MM': 'ငှားရမ်းမှုသွင်းငွေ', // Myanmar
        'km_KH': 'ដាក់ប្រាក់ថ្លៃឈ្នួល' // Cambodian
    },
};

/**
 * Retrieves the translation for a given text in the specified secondary language.
 * @param {string} englishText - The primary English text to translate.
 * @param {string} langCode - The code of the target secondary language (e.g., 'th_TH').
 * @returns {string} The translated text, or the original English text if no translation is found.
 */
export function getSecondaryTranslation(englishText, langCode) {
    const translations = secondaryTranslations[englishText];
    if (translations) {
        return translations[langCode] || translations['en_US']; // Fallback to English
    }
    return englishText;
}

